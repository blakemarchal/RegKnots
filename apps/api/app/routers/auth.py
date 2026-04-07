import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser, LoginRequest, RegisterRequest, TokenResponse
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.config import settings
from app.db import get_pool
from app.email import (
    send_password_changed_email,
    send_password_reset_email,
    send_verification_email,
    send_welcome_email,
)

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_PATH = "/"
_VALID_ROLES = {"captain", "mate", "engineer", "chief_engineer", "other"}


def _set_refresh_cookie(response: Response, raw_token: str) -> None:
    response.set_cookie(
        key=_COOKIE_NAME,
        value=raw_token,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        max_age=settings.refresh_token_expire_days * 24 * 3600,
        path=_COOKIE_PATH,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(key=_COOKIE_NAME, path=_COOKIE_PATH)


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, response: Response) -> TokenResponse:
    pool = await get_pool()

    existing = await pool.fetchval("SELECT id FROM users WHERE email = $1", data.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if data.role not in _VALID_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid role")

    hashed_pw = hash_password(data.password)
    trial_days = 14 if settings.pilot_mode else 7
    user = await pool.fetchrow(
        """
        INSERT INTO users (email, hashed_password, full_name, role, trial_ends_at)
        VALUES ($1, $2, $3, $4, NOW() + ($5 || ' days')::INTERVAL)
        RETURNING id, email, full_name, role, subscription_tier, is_admin, email_verified
        """,
        data.email,
        hashed_pw,
        data.full_name,
        data.role,
        str(trial_days),
    )

    # Auto-mark internal accounts
    base_email = data.email.split('+')[0] + '@' + data.email.split('@')[1] if '+' in data.email else data.email
    is_internal_check = await pool.fetchval(
        "SELECT is_internal FROM users WHERE email = $1", base_email
    )
    if is_internal_check:
        await pool.execute("UPDATE users SET is_internal = TRUE WHERE id = $1", user["id"])

    # Generate and store email verification token
    verification_token = secrets.token_urlsafe(32)
    await pool.execute(
        "UPDATE users SET email_verification_token = $1, email_verification_sent_at = NOW() WHERE id = $2",
        verification_token,
        user["id"],
    )

    access_token = create_access_token(
        str(user["id"]), user["email"], user["role"], user["subscription_tier"],
        full_name=user["full_name"], is_admin=user["is_admin"],
        email_verified=user["email_verified"],
    )
    raw_refresh, token_hash = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    await pool.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
        user["id"],
        token_hash,
        expires_at,
    )

    _set_refresh_cookie(response, raw_refresh)

    # Fire welcome email — non-blocking, failures don't affect registration
    try:
        await send_welcome_email(user["email"], user["full_name"])
    except Exception:
        pass

    # Fire verification email — non-blocking
    try:
        await send_verification_email(user["email"], user["full_name"], verification_token)
    except Exception:
        pass

    return TokenResponse(access_token=access_token)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, response: Response) -> TokenResponse:
    pool = await get_pool()

    user = await pool.fetchrow(
        "SELECT id, email, full_name, hashed_password, role, subscription_tier, is_admin, email_verified FROM users WHERE email = $1",
        data.email,
    )
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    access_token = create_access_token(
        str(user["id"]), user["email"], user["role"], user["subscription_tier"],
        full_name=user["full_name"], is_admin=user["is_admin"],
        email_verified=user["email_verified"],
    )
    raw_refresh, token_hash = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)

    await pool.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
        user["id"],
        token_hash,
        expires_at,
    )

    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token)


def _reject_refresh(detail: str) -> JSONResponse:
    """Return 401 with Set-Cookie that clears the refresh token cookie."""
    resp = JSONResponse(status_code=401, content={"detail": detail})
    resp.delete_cookie(key=_COOKIE_NAME, path=_COOKIE_PATH)
    return resp


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=_COOKIE_NAME),
):
    if not refresh_token:
        return _reject_refresh("No refresh token")

    pool = await get_pool()
    token_hash = hash_refresh_token(refresh_token)

    row = await pool.fetchrow(
        """
        SELECT rt.id, rt.user_id, rt.expires_at, rt.revoked, rt.revoked_at,
               u.email, u.full_name, u.role, u.subscription_tier, u.is_admin, u.email_verified
        FROM   refresh_tokens rt
        JOIN   users u ON u.id = rt.user_id
        WHERE  rt.token_hash = $1
        """,
        token_hash,
    )

    if not row:
        return _reject_refresh("Invalid refresh token")

    if row["revoked"]:
        # Check for race condition: if token was revoked very recently,
        # this is likely a concurrent request, not a replay attack
        revoked_at = row.get("revoked_at")
        if revoked_at and (datetime.now(timezone.utc) - revoked_at).total_seconds() < 10:
            return _reject_refresh("Token already rotated")
        # Genuine replay attack — revoke the entire user's session family
        await pool.execute(
            "UPDATE refresh_tokens SET revoked = TRUE, revoked_at = NOW() WHERE user_id = $1 AND NOT revoked",
            row["user_id"],
        )
        return _reject_refresh("Refresh token already used — all sessions revoked")

    if row["expires_at"] < datetime.now(timezone.utc):
        return _reject_refresh("Refresh token expired")

    # Rotate: invalidate old token, issue new pair
    await pool.execute(
        "UPDATE refresh_tokens SET revoked = TRUE, revoked_at = NOW() WHERE id = $1",
        row["id"],
    )

    raw_refresh, new_hash = create_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
    await pool.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at) VALUES ($1, $2, $3)",
        row["user_id"],
        new_hash,
        expires_at,
    )

    access_token = create_access_token(
        str(row["user_id"]), row["email"], row["role"], row["subscription_tier"],
        full_name=row["full_name"], is_admin=row["is_admin"],
        email_verified=row["email_verified"],
    )

    _set_refresh_cookie(response, raw_refresh)
    return TokenResponse(access_token=access_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=_COOKIE_NAME),
) -> None:
    if refresh_token:
        pool = await get_pool()
        token_hash = hash_refresh_token(refresh_token)
        await pool.execute(
            "UPDATE refresh_tokens SET revoked = TRUE WHERE token_hash = $1 AND NOT revoked",
            token_hash,
        )
    _clear_refresh_cookie(response)


# ── Profile & password management ─────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    full_name: str | None = None
    role: str | None = None


class ProfileResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@router.put("/profile", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ProfileResponse:
    if body.full_name is None and body.role is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one field to update",
        )
    if body.role is not None and body.role not in _VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"role must be one of: {', '.join(sorted(_VALID_ROLES))}",
        )

    pool = await get_pool()

    sets: list[str] = []
    params: list[object] = []
    idx = 1
    if body.full_name is not None:
        sets.append(f"full_name = ${idx}")
        params.append(body.full_name.strip())
        idx += 1
    if body.role is not None:
        sets.append(f"role = ${idx}")
        params.append(body.role)
        idx += 1

    params.append(uuid.UUID(user.user_id))
    row = await pool.fetchrow(
        f"""
        UPDATE users SET {', '.join(sets)}
        WHERE id = ${idx}
        RETURNING id, email, full_name, role, subscription_tier, is_admin, email_verified
        """,
        *params,
    )

    access_token = create_access_token(
        str(row["id"]), row["email"], row["role"], row["subscription_tier"],
        full_name=row["full_name"], is_admin=row["is_admin"],
        email_verified=row["email_verified"],
    )
    return ProfileResponse(access_token=access_token)


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


@router.put("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: PasswordChange,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="New password must be at least 8 characters",
        )

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT hashed_password FROM users WHERE id = $1",
        uuid.UUID(user.user_id),
    )
    if not row or not verify_password(body.current_password, row["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Current password is incorrect",
        )

    new_hash = hash_password(body.new_password)
    await pool.execute(
        "UPDATE users SET hashed_password = $1 WHERE id = $2",
        new_hash,
        uuid.UUID(user.user_id),
    )

    try:
        await send_password_changed_email(user.email, user.full_name or user.email)
    except Exception:
        pass


# ── Password reset (unauthenticated) ──────────────────────────────────────────

_RESET_TOKEN_EXPIRE_HOURS = 1


def _hash_reset_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


class ForgotPasswordRequest(BaseModel):
    email: str


@router.post("/forgot-password", status_code=status.HTTP_200_OK)
async def forgot_password(body: ForgotPasswordRequest) -> dict:
    pool = await get_pool()
    user = await pool.fetchrow(
        "SELECT id, email, full_name FROM users WHERE email = $1",
        body.email.strip().lower(),
    )

    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_reset_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=_RESET_TOKEN_EXPIRE_HOURS)

        await pool.execute(
            """
            INSERT INTO password_reset_tokens (user_id, token_hash, expires_at)
            VALUES ($1, $2, $3)
            """,
            user["id"],
            token_hash,
            expires_at,
        )

        try:
            await send_password_reset_email(user["email"], raw_token)
        except Exception:
            pass

    # Always return the same response — don't reveal whether email exists
    return {"detail": "If that email is registered, you'll receive a reset link shortly"}


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


@router.post("/reset-password", status_code=status.HTTP_200_OK)
async def reset_password(body: ResetPasswordRequest) -> dict:
    if len(body.new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Password must be at least 8 characters",
        )

    token_hash = _hash_reset_token(body.token)
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT id, user_id, expires_at, used
        FROM password_reset_tokens
        WHERE token_hash = $1
        """,
        token_hash,
    )

    if not row or row["used"] or row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset link",
        )

    new_hash = hash_password(body.new_password)
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE users SET hashed_password = $1 WHERE id = $2",
                new_hash,
                row["user_id"],
            )
            await conn.execute(
                "UPDATE password_reset_tokens SET used = TRUE WHERE id = $1",
                row["id"],
            )

    # Fetch user for notification email — non-fatal if it fails
    reset_user = await pool.fetchrow(
        "SELECT email, full_name FROM users WHERE id = $1",
        row["user_id"],
    )
    if reset_user:
        try:
            await send_password_changed_email(
                reset_user["email"],
                reset_user["full_name"] or reset_user["email"],
            )
        except Exception:
            pass

    return {"detail": "Password updated successfully"}


# ── Email verification ────────────────────────────────────────────────────────


@router.get("/verify-email", status_code=status.HTTP_200_OK)
async def verify_email(token: str) -> dict:
    pool = await get_pool()

    user = await pool.fetchrow(
        "SELECT id, email, email_verified FROM users WHERE email_verification_token = $1",
        token,
    )

    if not user:
        raise HTTPException(status_code=400, detail="Invalid verification link")

    if user["email_verified"]:
        return {"detail": "Email already verified", "already_verified": True}

    await pool.execute(
        "UPDATE users SET email_verified = TRUE, email_verification_token = NULL WHERE id = $1",
        user["id"],
    )

    return {"detail": "Email verified successfully", "already_verified": False}


@router.post("/resend-verification", status_code=status.HTTP_200_OK)
async def resend_verification(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    pool = await get_pool()

    row = await pool.fetchrow(
        "SELECT email, full_name, email_verified, email_verification_sent_at FROM users WHERE id = $1",
        uuid.UUID(user.user_id),
    )

    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    if row["email_verified"]:
        return {"detail": "Email already verified"}

    # Rate limit: max once per 60 seconds
    if row["email_verification_sent_at"]:
        elapsed = (
            datetime.now(timezone.utc) - row["email_verification_sent_at"]
        ).total_seconds()
        if elapsed < 60:
            raise HTTPException(
                status_code=429,
                detail="Please wait before requesting another verification email",
            )

    new_token = secrets.token_urlsafe(32)
    await pool.execute(
        "UPDATE users SET email_verification_token = $1, email_verification_sent_at = NOW() WHERE id = $2",
        new_token,
        uuid.UUID(user.user_id),
    )

    try:
        await send_verification_email(row["email"], row["full_name"], new_token)
    except Exception:
        raise HTTPException(
            status_code=502, detail="Failed to send verification email"
        )

    return {"detail": "Verification email sent"}

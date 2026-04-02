from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, HTTPException, Response, status

from app.auth.schemas import LoginRequest, RegisterRequest, TokenResponse
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)
from app.config import settings
from app.db import get_pool

router = APIRouter(prefix="/auth", tags=["auth"])

_COOKIE_NAME = "refresh_token"
_COOKIE_PATH = "/"


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

    if data.role not in ("captain", "mate", "engineer", "other"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid role")

    hashed_pw = hash_password(data.password)
    user = await pool.fetchrow(
        """
        INSERT INTO users (email, hashed_password, full_name, role)
        VALUES ($1, $2, $3, $4)
        RETURNING id, email, role, subscription_tier
        """,
        data.email,
        hashed_pw,
        data.full_name,
        data.role,
    )

    access_token = create_access_token(
        str(user["id"]), user["email"], user["role"], user["subscription_tier"]
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


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, response: Response) -> TokenResponse:
    pool = await get_pool()

    user = await pool.fetchrow(
        "SELECT id, email, hashed_password, role, subscription_tier FROM users WHERE email = $1",
        data.email,
    )
    if not user or not verify_password(data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
        )

    access_token = create_access_token(
        str(user["id"]), user["email"], user["role"], user["subscription_tier"]
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


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None, alias=_COOKIE_NAME),
) -> TokenResponse:
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    pool = await get_pool()
    token_hash = hash_refresh_token(refresh_token)

    row = await pool.fetchrow(
        """
        SELECT rt.id, rt.user_id, rt.expires_at, rt.revoked,
               u.email, u.role, u.subscription_tier
        FROM   refresh_tokens rt
        JOIN   users u ON u.id = rt.user_id
        WHERE  rt.token_hash = $1
        """,
        token_hash,
    )

    if not row:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    if row["revoked"]:
        # Token reuse detected — revoke the entire user's session family
        await pool.execute(
            "UPDATE refresh_tokens SET revoked = TRUE WHERE user_id = $1 AND NOT revoked",
            row["user_id"],
        )
        _clear_refresh_cookie(response)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token already used — all sessions revoked",
        )

    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")

    # Rotate: invalidate old token, issue new pair
    await pool.execute(
        "UPDATE refresh_tokens SET revoked = TRUE WHERE id = $1",
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
        str(row["user_id"]), row["email"], row["role"], row["subscription_tier"]
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

"""Admin dashboard endpoints — stats, user list, model usage, pilot reset, email testing."""

import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


async def require_admin(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


# ── Stats ────────────────────────────────────────────────────────────────────────

class AdminStats(BaseModel):
    total_users: int
    active_users_24h: int
    active_users_7d: int
    total_conversations: int
    total_messages: int
    messages_today: int
    messages_7d: int
    pro_subscribers: int
    trial_active: int
    trial_expired: int
    message_limit_reached: int
    total_chunks: int
    chunks_by_source: dict[str, int]
    citation_errors_7d: int


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminStats:
    pool = await get_pool()
    async with pool.acquire() as conn:
        total_users = await conn.fetchval("SELECT COUNT(*) FROM users")

        active_users_24h = await conn.fetchval(
            "SELECT COUNT(DISTINCT m.conversation_id) FROM messages m "
            "JOIN conversations c ON c.id = m.conversation_id "
            "WHERE m.created_at > NOW() - INTERVAL '24 hours'"
        )
        # Use distinct user_id from conversations joined to messages
        active_users_24h = await conn.fetchval(
            "SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
            "JOIN messages m ON m.conversation_id = c.id "
            "WHERE m.created_at > NOW() - INTERVAL '24 hours'"
        )
        active_users_7d = await conn.fetchval(
            "SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
            "JOIN messages m ON m.conversation_id = c.id "
            "WHERE m.created_at > NOW() - INTERVAL '7 days'"
        )

        total_conversations = await conn.fetchval("SELECT COUNT(*) FROM conversations")
        total_messages = await conn.fetchval("SELECT COUNT(*) FROM messages")

        messages_today = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')"
        )
        messages_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM messages WHERE created_at > NOW() - INTERVAL '7 days'"
        )

        pro_subscribers = await conn.fetchval(
            "SELECT COUNT(*) FROM users "
            "WHERE subscription_tier = 'pro' AND subscription_status = 'active'"
        )
        trial_active = await conn.fetchval(
            "SELECT COUNT(*) FROM users "
            "WHERE trial_ends_at > NOW() AND subscription_tier = 'free'"
        )
        trial_expired = await conn.fetchval(
            "SELECT COUNT(*) FROM users "
            "WHERE trial_ends_at <= NOW() AND subscription_tier = 'free'"
        )
        message_limit_reached = await conn.fetchval(
            "SELECT COUNT(*) FROM users "
            "WHERE subscription_tier = 'free' AND message_count >= 50"
        )

        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM regulations")

        chunk_rows = await conn.fetch(
            "SELECT source, COUNT(*) AS cnt FROM regulations GROUP BY source ORDER BY source"
        )
        chunks_by_source = {r["source"]: r["cnt"] for r in chunk_rows}

        citation_errors_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM citation_errors WHERE created_at > NOW() - INTERVAL '7 days'"
        )

    return AdminStats(
        total_users=total_users,
        active_users_24h=active_users_24h,
        active_users_7d=active_users_7d,
        total_conversations=total_conversations,
        total_messages=total_messages,
        messages_today=messages_today,
        messages_7d=messages_7d,
        pro_subscribers=pro_subscribers,
        trial_active=trial_active,
        trial_expired=trial_expired,
        message_limit_reached=message_limit_reached,
        total_chunks=total_chunks,
        chunks_by_source=chunks_by_source,
        citation_errors_7d=citation_errors_7d,
    )


# ── Users ────────────────────────────────────────────────────────────────────────

class AdminUser(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    subscription_tier: str
    subscription_status: str
    message_count: int
    trial_ends_at: str | None
    created_at: str
    is_admin: bool


@router.get("/users", response_model=list[AdminUser])
async def list_users(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AdminUser]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, email, full_name, role, subscription_tier,
               subscription_status, message_count, trial_ends_at, created_at, is_admin
        FROM users
        ORDER BY created_at DESC
        LIMIT $1 OFFSET $2
        """,
        limit,
        offset,
    )
    return [
        AdminUser(
            id=str(r["id"]),
            email=r["email"],
            full_name=r["full_name"],
            role=r["role"],
            subscription_tier=r["subscription_tier"],
            subscription_status=r["subscription_status"],
            message_count=r["message_count"],
            trial_ends_at=r["trial_ends_at"].isoformat() if r["trial_ends_at"] else None,
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
            is_admin=r["is_admin"],
        )
        for r in rows
    ]


# ── Model usage ──────────────────────────────────────────────────────────────────

class ModelUsage(BaseModel):
    model: str
    message_count: int
    total_input_tokens: int
    total_output_tokens: int


@router.get("/model-usage", response_model=list[ModelUsage])
async def model_usage(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> list[ModelUsage]:
    pool = await get_pool()
    # messages table has model_used and tokens_used columns
    # tokens_used is a single int (no input/output split yet)
    rows = await pool.fetch(
        """
        SELECT COALESCE(model_used, 'unknown') AS model,
               COUNT(*) AS msg_count,
               COALESCE(SUM(tokens_used), 0) AS total_tokens
        FROM messages
        WHERE role = 'assistant'
        GROUP BY model_used
        ORDER BY msg_count DESC
        """
    )
    return [
        ModelUsage(
            model=r["model"],
            message_count=r["msg_count"],
            total_input_tokens=0,  # TODO: wire up when input/output token split is tracked
            total_output_tokens=r["total_tokens"],
        )
        for r in rows
    ]


# ── Pilot reset ────────────────────────────────────────────────────────────────

class ResetResult(BaseModel):
    reset_count: int


@router.post("/reset-user/{user_id}", response_model=ResetResult)
async def reset_user(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> ResetResult:
    """Reset a single user's pilot state: zero message_count, restart trial, delete conversations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow("SELECT id, email FROM users WHERE id = $1", user_id)
            if not row:
                raise HTTPException(status_code=404, detail="User not found")

            await conn.execute(
                """
                UPDATE users
                SET message_count = 0,
                    trial_ends_at = NOW() + INTERVAL '14 days',
                    subscription_status = 'active'
                WHERE id = $1
                """,
                user_id,
            )

            await conn.execute(
                """
                DELETE FROM messages WHERE conversation_id IN (
                    SELECT id FROM conversations WHERE user_id = $1
                )
                """,
                user_id,
            )
            await conn.execute("DELETE FROM conversations WHERE user_id = $1", user_id)

    logger.info("Admin %s reset user %s (%s)", admin.email, user_id, row["email"])
    return ResetResult(reset_count=1)


@router.post("/reset-all-pilots", response_model=ResetResult)
async def reset_all_pilots(
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> ResetResult:
    """Reset ALL non-admin users: zero message_count, restart trial, delete conversations."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            rows = await conn.fetch("SELECT id FROM users WHERE is_admin = false")
            user_ids = [r["id"] for r in rows]

            if not user_ids:
                return ResetResult(reset_count=0)

            await conn.execute(
                """
                UPDATE users
                SET message_count = 0,
                    trial_ends_at = NOW() + INTERVAL '14 days',
                    subscription_status = 'active'
                WHERE is_admin = false
                """
            )

            await conn.execute(
                """
                DELETE FROM messages WHERE conversation_id IN (
                    SELECT id FROM conversations WHERE user_id = ANY($1::uuid[])
                )
                """,
                user_ids,
            )
            await conn.execute(
                "DELETE FROM conversations WHERE user_id = ANY($1::uuid[])",
                user_ids,
            )

    logger.info("Admin %s reset %d pilot accounts", admin.email, len(user_ids))
    return ResetResult(reset_count=len(user_ids))


# ── Admin write actions ────────────────────────────────────────────────────────

class ExtendTrialResult(BaseModel):
    trial_ends_at: str


@router.post("/extend-trial/{user_id}", response_model=ExtendTrialResult)
async def extend_trial(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> ExtendTrialResult:
    """Extend a user's trial by 14 days from now."""
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        UPDATE users
        SET trial_ends_at = NOW() + INTERVAL '14 days',
            trial_reminder_sent = FALSE
        WHERE id = $1
        RETURNING trial_ends_at
        """,
        user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("Admin %s extended trial for %s", admin.email, user_id)
    return ExtendTrialResult(trial_ends_at=row["trial_ends_at"].isoformat())


class AdminActionResult(BaseModel):
    ok: bool


@router.post("/grant-pro/{user_id}", response_model=AdminActionResult)
async def grant_pro(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminActionResult:
    """Manually grant pro tier to a user."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE users
        SET subscription_tier = 'pro',
            subscription_status = 'active'
        WHERE id = $1
        """,
        user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("Admin %s granted pro to %s", admin.email, user_id)
    return AdminActionResult(ok=True)


@router.post("/revoke-pro/{user_id}", response_model=AdminActionResult)
async def revoke_pro(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> AdminActionResult:
    """Revoke pro tier and revert to free."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE users
        SET subscription_tier = 'free',
            subscription_status = 'inactive'
        WHERE id = $1
        """,
        user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("Admin %s revoked pro from %s", admin.email, user_id)
    return AdminActionResult(ok=True)


# ── Email testing ─────────────────────────────────────────────────────────────

EmailType = Literal["welcome", "password_reset", "trial_expiry", "pilot_ended", "waitlist_confirmed"]


class TestEmailRequest(BaseModel):
    type: EmailType
    recipient: str | None = None


class TestEmailResult(BaseModel):
    success: bool
    type: str
    recipient: str


@router.post("/test-email", response_model=TestEmailResult)
async def send_test_email(
    body: TestEmailRequest,
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> TestEmailResult:
    """Send a test email of any type to the admin's own address (or a specified recipient)."""
    from app.email import (
        send_welcome_email,
        send_password_reset_email,
        send_trial_expiring_email,
        send_pilot_ended_email,
        send_waitlist_confirmed_email,
    )

    recipient = body.recipient or admin.email

    try:
        if body.type == "welcome":
            await send_welcome_email(recipient, "Test Mariner")
        elif body.type == "password_reset":
            await send_password_reset_email(recipient, "test-reset-token-abc123")
        elif body.type == "trial_expiry":
            await send_trial_expiring_email(recipient, "Test Mariner", 37)
        elif body.type == "pilot_ended":
            await send_pilot_ended_email(recipient, "Test Mariner")
        elif body.type == "waitlist_confirmed":
            await send_waitlist_confirmed_email(recipient, "Test Mariner")
    except Exception as exc:
        logger.error("Test email failed type=%s: %s", body.type, exc)
        raise HTTPException(status_code=502, detail=str(exc))

    logger.info("Admin %s sent test email type=%s to=%s", admin.email, body.type, recipient)
    return TestEmailResult(success=True, type=body.type, recipient=recipient)

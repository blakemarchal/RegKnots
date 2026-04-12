"""Admin dashboard endpoints — stats, user list, model usage, pilot reset, email testing, Sentry, export."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Read-only admins: can view dashboard but cannot perform mutations
# (Karynn promoted to full admin 2026-04-12)
READONLY_ADMIN_EMAILS: set[str] = set()


async def require_admin(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUser:
    if not user.is_admin and user.email not in READONLY_ADMIN_EMAILS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_write_admin(
    user: Annotated[CurrentUser, Depends(require_admin)],
) -> CurrentUser:
    if user.email in READONLY_ADMIN_EMAILS:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Read-only admin access")
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
    # Subscription breakdown
    subs_monthly: int
    subs_annual: int
    subs_paused: int


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> AdminStats:
    pool = await get_pool()
    # When filtering, exclude users where is_internal = TRUE and their data
    uf = " AND u.is_internal IS NOT TRUE" if exclude_internal else ""
    muf = (
        " AND m.conversation_id IN (SELECT c2.id FROM conversations c2 JOIN users u2 ON u2.id = c2.user_id WHERE u2.is_internal IS NOT TRUE)"
        if exclude_internal else ""
    )
    async with pool.acquire() as conn:
        total_users = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u WHERE 1=1{uf}"
        )

        active_users_24h = await conn.fetchval(
            f"SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
            f"JOIN messages m ON m.conversation_id = c.id "
            f"JOIN users u ON u.id = c.user_id "
            f"WHERE m.created_at > NOW() - INTERVAL '24 hours'{uf}"
        )
        active_users_7d = await conn.fetchval(
            f"SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
            f"JOIN messages m ON m.conversation_id = c.id "
            f"JOIN users u ON u.id = c.user_id "
            f"WHERE m.created_at > NOW() - INTERVAL '7 days'{uf}"
        )

        total_conversations = await conn.fetchval(
            f"SELECT COUNT(*) FROM conversations c JOIN users u ON u.id = c.user_id WHERE 1=1{uf}"
            if exclude_internal else "SELECT COUNT(*) FROM conversations"
        )
        total_messages = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages m WHERE 1=1{muf}"
            if exclude_internal else "SELECT COUNT(*) FROM messages"
        )

        messages_today = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages m WHERE m.created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'){muf}"
        )
        messages_7d = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages m WHERE m.created_at > NOW() - INTERVAL '7 days'{muf}"
        )

        pro_subscribers = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u "
            f"WHERE subscription_tier = 'pro' AND subscription_status = 'active'{uf}"
        )
        trial_active = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u "
            f"WHERE trial_ends_at > NOW() AND subscription_tier = 'free'{uf}"
        )
        trial_expired = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u "
            f"WHERE trial_ends_at <= NOW() AND subscription_tier = 'free'{uf}"
        )
        message_limit_reached = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u "
            f"WHERE subscription_tier = 'free' AND message_count >= 50{uf}"
        )

        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM regulations")

        chunk_rows = await conn.fetch(
            "SELECT source, COUNT(*) AS cnt FROM regulations GROUP BY source ORDER BY source"
        )
        chunks_by_source = {r["source"]: r["cnt"] for r in chunk_rows}

        citation_errors_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM citation_errors ce "
            "JOIN conversations c ON c.id = ce.conversation_id "
            "JOIN users u ON u.id = c.user_id "
            f"WHERE ce.created_at > NOW() - INTERVAL '7 days'{uf}"
            if exclude_internal else
            "SELECT COUNT(*) FROM citation_errors WHERE created_at > NOW() - INTERVAL '7 days'"
        )

        sub_row = await conn.fetchrow(
            f"""
            SELECT
              COUNT(*) FILTER (
                WHERE subscription_tier = 'pro'
                  AND subscription_status = 'active'
                  AND billing_interval = 'month'
              ) AS monthly,
              COUNT(*) FILTER (
                WHERE subscription_tier = 'pro'
                  AND subscription_status = 'active'
                  AND billing_interval = 'year'
              ) AS annual,
              COUNT(*) FILTER (WHERE subscription_status = 'paused') AS paused
            FROM users u
            WHERE is_admin = false{uf}
            """
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
        subs_monthly=sub_row["monthly"] or 0,
        subs_annual=sub_row["annual"] or 0,
        subs_paused=sub_row["paused"] or 0,
    )


# ── Users ────────────────────────────────────────────────────────────────────────

class AdminUser(BaseModel):
    id: str
    email: str
    full_name: str | None
    role: str
    subscription_tier: str
    subscription_status: str
    billing_interval: str | None
    cancel_at_period_end: bool
    current_period_end: str | None
    message_count: int
    vessel_count: int
    trial_ends_at: str | None
    created_at: str
    last_active_at: str | None
    is_admin: bool


@router.get("/users", response_model=list[AdminUser])
async def list_users(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    exclude_internal: bool = Query(default=False),
) -> list[AdminUser]:
    pool = await get_pool()
    where = "WHERE u.is_internal IS NOT TRUE" if exclude_internal else ""
    rows = await pool.fetch(
        f"""
        SELECT u.id, u.email, u.full_name, u.role, u.subscription_tier,
               u.subscription_status, u.billing_interval, u.cancel_at_period_end,
               u.current_period_end, u.message_count, u.trial_ends_at,
               u.created_at, u.is_admin,
               (SELECT COUNT(*) FROM vessels v WHERE v.user_id = u.id) AS vessel_count,
               (
                 SELECT MAX(m.created_at)
                 FROM messages m
                 JOIN conversations c ON c.id = m.conversation_id
                 WHERE c.user_id = u.id
               ) AS last_active_at
        FROM users u
        {where}
        ORDER BY u.created_at DESC
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
            billing_interval=r["billing_interval"],
            cancel_at_period_end=r["cancel_at_period_end"],
            current_period_end=r["current_period_end"].isoformat() if r["current_period_end"] else None,
            message_count=r["message_count"],
            vessel_count=r["vessel_count"] or 0,
            trial_ends_at=r["trial_ends_at"].isoformat() if r["trial_ends_at"] else None,
            created_at=r["created_at"].isoformat() if r["created_at"] else None,
            last_active_at=r["last_active_at"].isoformat() if r["last_active_at"] else None,
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
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
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
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
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
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
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
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
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


class DeleteUserResult(BaseModel):
    deleted: bool
    email: str


@router.delete("/users/{user_id}", response_model=DeleteUserResult)
async def delete_user(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> DeleteUserResult:
    """Permanently delete a user and all cascading data (conversations, messages,
    vessels, refresh_tokens, support_tickets, etc.). Admin users cannot be deleted."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")

    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, email, is_admin FROM users WHERE id = $1",
        uid,
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    if row["is_admin"]:
        raise HTTPException(status_code=403, detail="Cannot delete admin users")

    try:
        await pool.execute("DELETE FROM users WHERE id = $1", uid)
    except asyncpg.exceptions.ForeignKeyViolationError as exc:
        logger.exception("FK violation deleting user %s", user_id)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete user: foreign key constraint "
                f"{exc.constraint_name or 'unknown'} blocks the cascade. "
                "A referencing table is missing ON DELETE CASCADE."
            ),
        ) from exc
    logger.warning("Admin %s deleted user %s (%s)", admin.email, row["email"], user_id)
    return DeleteUserResult(deleted=True, email=row["email"])


@router.post("/revoke-pro/{user_id}", response_model=AdminActionResult)
async def revoke_pro(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
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


# ── Notifications (admin) ───────────────────────────────────────────────────


class CreateNotificationRequest(BaseModel):
    title: str
    body: str
    notification_type: str = "regulation_update"
    source: str | None = None
    link_url: str | None = None


@router.get("/notifications")
async def list_all_notifications(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> list[dict[str, Any]]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, title, body, notification_type, source, is_active, created_at
        FROM notifications
        ORDER BY created_at DESC
        LIMIT 20
        """
    )
    return [
        {
            "id": str(r["id"]),
            "title": r["title"],
            "body": r["body"],
            "notification_type": r["notification_type"],
            "source": r["source"],
            "is_active": r["is_active"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


@router.post("/notifications")
async def create_notification(
    body: CreateNotificationRequest,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> dict[str, str]:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO notifications (title, body, notification_type, source, link_url)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, created_at
        """,
        body.title,
        body.body,
        body.notification_type,
        body.source,
        body.link_url,
    )
    logger.info("Admin %s created notification %s", admin.email, row["id"])
    return {"id": str(row["id"]), "created_at": row["created_at"].isoformat()}


@router.patch("/notifications/{notification_id}")
async def toggle_notification(
    notification_id: str,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> dict[str, str]:
    try:
        nid = uuid.UUID(notification_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid notification id")
    pool = await get_pool()
    result = await pool.execute(
        "UPDATE notifications SET is_active = NOT is_active WHERE id = $1",
        nid,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Notification not found")
    logger.info("Admin %s toggled notification %s", admin.email, notification_id)
    return {"status": "toggled"}


# ── Subscription audit ──────────────────────────────────────────────────────


@router.get("/subscription-audit/{email}")
async def subscription_audit(
    email: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> dict[str, Any]:
    """Check a user's subscription state in both our DB and Stripe."""
    pool = await get_pool()

    row = await pool.fetchrow(
        """
        SELECT id, email, full_name, subscription_tier, subscription_status,
               stripe_customer_id, stripe_subscription_id, cancel_at_period_end,
               current_period_end, billing_interval
        FROM users WHERE email = $1
        """,
        email,
    )
    if not row:
        raise HTTPException(status_code=404, detail="User not found")

    result: dict[str, Any] = {
        "db": {
            k: str(v) if isinstance(v, (datetime, uuid.UUID)) else v
            for k, v in dict(row).items()
        },
        "stripe": None,
    }

    if row["stripe_subscription_id"]:
        try:
            import stripe as _stripe
            _stripe.api_key = settings.stripe_secret_key
            sub = _stripe.Subscription.retrieve(row["stripe_subscription_id"])
            result["stripe"] = {
                "id": sub.id,
                "status": sub.status,
                "cancel_at_period_end": sub.cancel_at_period_end,
                "cancel_at": getattr(sub, "cancel_at", None),
                "canceled_at": getattr(sub, "canceled_at", None),
                "current_period_end": sub.current_period_end,
            }
        except Exception as exc:
            result["stripe"] = {"error": str(exc)}

    return result


# ── Trial expiry simulator ────────────────────────────────────────────────────


@router.post("/simulate-expiry/{user_id}", response_model=AdminActionResult)
async def simulate_expiry(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> AdminActionResult:
    """Set a user's trial_ends_at to yesterday to simulate trial expiration."""
    pool = await get_pool()
    result = await pool.execute(
        """
        UPDATE users
        SET trial_ends_at = NOW() - INTERVAL '1 day'
        WHERE id = $1
        """,
        user_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")
    logger.info("Admin %s simulated expiry for %s", admin.email, user_id)
    return AdminActionResult(ok=True)


# ── Citation errors ──────────────────────────────────────────────────────────


class CitationError(BaseModel):
    id: str
    conversation_id: str
    unverified_citation: str
    model_used: str | None
    message_preview: str
    created_at: str


@router.get("/citation-errors", response_model=list[CitationError])
async def list_citation_errors(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=200),
    exclude_internal: bool = Query(default=False),
) -> list[CitationError]:
    """Return recent citation errors for the admin dashboard."""
    pool = await get_pool()
    if exclude_internal:
        rows = await pool.fetch(
            """
            SELECT ce.id, ce.conversation_id, ce.unverified_citation, ce.model_used,
                   ce.message_content AS message_preview, ce.created_at
            FROM citation_errors ce
            JOIN conversations c ON c.id = ce.conversation_id
            JOIN users u ON u.id = c.user_id
            WHERE u.is_internal IS NOT TRUE
            ORDER BY ce.created_at DESC
            LIMIT $1
            """,
            limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, conversation_id, unverified_citation, model_used,
                   message_content AS message_preview, created_at
            FROM citation_errors
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
    return [
        CitationError(
            id=str(r["id"]),
            conversation_id=str(r["conversation_id"]),
            unverified_citation=r["unverified_citation"],
            model_used=r["model_used"],
            message_preview=r["message_preview"] or "",
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
        )
        for r in rows
    ]


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
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
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


# ── Custom email blast ───────────────────────────────────────────────────────


class CustomEmailCountResult(BaseModel):
    count: int


@router.get("/custom-email-count", response_model=CustomEmailCountResult)
async def get_custom_email_count(
    filter: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> CustomEmailCountResult:
    """Preview how many users match a recipient filter."""
    clause = {
        "all": "subscription_status = 'active'",
        "pro": "subscription_tier = 'solo' AND subscription_status = 'active'",
        "trial": "trial_ends_at IS NOT NULL AND trial_ends_at > NOW() AND subscription_tier = 'free'",
    }.get(filter, "FALSE")
    count = await pool.fetchval(
        f"SELECT count(*) FROM users WHERE {clause} AND is_internal = FALSE"
    )
    return CustomEmailCountResult(count=int(count or 0))


class CustomEmailRequest(BaseModel):
    subject: str
    body_text: str
    recipient_filter: str  # "all" | "pro" | "trial" | "custom"
    custom_emails: list[str] | None = None


class CustomEmailResult(BaseModel):
    sent: int
    failed: int
    failed_emails: list[str]


@router.post("/send-custom-email", response_model=CustomEmailResult)
async def send_custom_email_blast(
    body: CustomEmailRequest,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> CustomEmailResult:
    """Send a custom admin-composed email to filtered recipients."""
    import asyncio as _asyncio

    from app.email import send_custom_email, send_with_throttle, RESEND_THROTTLE_SECONDS

    # Resolve recipients
    if body.recipient_filter == "custom":
        if not body.custom_emails:
            raise HTTPException(status_code=400, detail="custom_emails required for custom filter")
        emails = body.custom_emails
    else:
        filter_clause = {
            "all": "subscription_status = 'active'",
            "pro": "subscription_tier = 'solo' AND subscription_status = 'active'",
            "trial": "trial_ends_at IS NOT NULL AND trial_ends_at > NOW() AND subscription_tier = 'free'",
        }.get(body.recipient_filter)
        if not filter_clause:
            raise HTTPException(status_code=400, detail=f"Unknown filter: {body.recipient_filter}")

        rows = await pool.fetch(
            f"SELECT email FROM users WHERE {filter_clause} AND is_internal = FALSE"
        )
        emails = [r["email"] for r in rows]

    if not emails:
        return CustomEmailResult(sent=0, failed=0, failed_emails=[])

    sent = 0
    failed_emails: list[str] = []

    for i, email in enumerate(emails):
        try:
            await send_with_throttle(
                lambda e=email: send_custom_email(e, body.subject, body.body_text),
                label=email,
            )
            sent += 1
        except Exception as exc:
            logger.warning("Custom email failed to %s: %s", email, exc)
            failed_emails.append(email)

        if i < len(emails) - 1:
            await _asyncio.sleep(RESEND_THROTTLE_SECONDS)

    logger.info(
        "Admin %s sent custom email '%s' filter=%s: sent=%d failed=%d",
        admin.email, body.subject, body.recipient_filter, sent, len(failed_emails),
    )
    return CustomEmailResult(sent=sent, failed=len(failed_emails), failed_emails=failed_emails)


# ── Founding member email ────────────────────────────────────────────────────


class FoundingEmailRecipient(BaseModel):
    email: str
    name: str | None


class FoundingEmailPreview(BaseModel):
    subject: str
    recipients: list[FoundingEmailRecipient]
    total_count: int
    sample_html: str


class FoundingEmailSendResult(BaseModel):
    # Spec: {"sent": 12, "failed": 2, "failed_emails": ["x@y.com", ...]}
    sent: int
    failed: int
    failed_emails: list[str]
    # Back-compat alias preserved so any older frontend build that reads
    # `sent_count` still works until its next deploy.
    sent_count: int


class FoundingEmailTestResult(BaseModel):
    sent_to: str


@router.get("/founding-email/preview", response_model=FoundingEmailPreview)
async def founding_email_preview(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> FoundingEmailPreview:
    """Preview the founding member email and list pending recipients."""
    from app.email import render_founding_member_email

    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT email, full_name
        FROM users
        WHERE is_admin = false
          AND founding_email_sent = false
        ORDER BY created_at ASC
        """
    )
    recipients = [
        FoundingEmailRecipient(email=r["email"], name=r["full_name"]) for r in rows
    ]
    sample_name = recipients[0].name if recipients else None
    subject, sample_html = render_founding_member_email(sample_name)
    return FoundingEmailPreview(
        subject=subject,
        recipients=recipients,
        total_count=len(recipients),
        sample_html=sample_html,
    )


@router.post("/founding-email/test", response_model=FoundingEmailTestResult)
async def founding_email_test(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> FoundingEmailTestResult:
    """Send the founding member email to the requesting admin only (no DB writes)."""
    from app.email import send_founding_member_email

    try:
        await send_founding_member_email(admin.email, admin.full_name)
    except Exception as exc:
        logger.error("Founding email test send failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc))

    logger.info("Admin %s sent founding-email test to self", admin.email)
    return FoundingEmailTestResult(sent_to=admin.email)


@router.post("/founding-email/send", response_model=FoundingEmailSendResult)
async def founding_email_send(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    force: bool = Query(default=False),
) -> FoundingEmailSendResult:
    """Send the founding member email to all non-admin users who haven't received it.

    Guard: if any sends have already happened (any user has founding_email_sent=true)
    require ?force=true to send again to the remaining users.
    """
    import asyncio as _asyncio
    from app.email import (
        RESEND_THROTTLE_SECONDS,
        send_founding_member_email,
        send_with_throttle,
    )

    pool = await get_pool()

    already_sent = await pool.fetchval(
        "SELECT COUNT(*) FROM users WHERE founding_email_sent = true"
    )
    if already_sent and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Founding email already sent to {already_sent} users. "
                "Pass ?force=true to send to remaining recipients."
            ),
        )

    rows = await pool.fetch(
        """
        SELECT id, email, full_name
        FROM users
        WHERE is_admin = false
          AND founding_email_sent = false
        ORDER BY created_at ASC
        """
    )

    sent_count = 0
    failed_emails: list[str] = []
    total = len(rows)
    for idx, row in enumerate(rows):
        email = row["email"]
        try:
            await send_with_throttle(
                lambda email=email, name=row["full_name"]: send_founding_member_email(email, name),
                label=email,
            )
        except Exception as exc:
            logger.error("Founding email send failed for %s: %s", email, exc)
            failed_emails.append(email)
            # Still sleep between sends — a failure doesn't earn us a free
            # send slot from Resend, and back-off helps the retry storm.
            if idx < total - 1:
                await _asyncio.sleep(RESEND_THROTTLE_SECONDS)
            continue

        try:
            await pool.execute(
                "UPDATE users SET founding_email_sent = true WHERE id = $1",
                row["id"],
            )
            sent_count += 1
        except Exception as exc:
            logger.error("Failed to mark founding_email_sent for %s: %s", email, exc)
            failed_emails.append(email)

        # Space out successive sends under Resend's 5 req/s ceiling.
        if idx < total - 1:
            await _asyncio.sleep(RESEND_THROTTLE_SECONDS)

    logger.info(
        "Admin %s ran founding-email/send: sent=%d failed=%d force=%s",
        admin.email, sent_count, len(failed_emails), force,
    )
    return FoundingEmailSendResult(
        sent=sent_count,
        failed=len(failed_emails),
        failed_emails=failed_emails,
        sent_count=sent_count,
    )


# ── Sentry issues ────────────────────────────────────────────────────────────

# Default scope: queried when SENTRY_PROJECT env var is unset.
DEFAULT_SENTRY_PROJECTS = ["regknots-api", "regknots-web"]


def _resolve_sentry_projects() -> list[str]:
    """Return the project slug list to query based on SENTRY_PROJECT env var.

    - Unset → DEFAULT_SENTRY_PROJECTS (both frontend and backend)
    - "foo" → ["foo"]
    - "foo,bar" → ["foo", "bar"]
    """
    raw = (settings.sentry_project or "").strip()
    if not raw:
        return DEFAULT_SENTRY_PROJECTS
    return [p.strip() for p in raw.split(",") if p.strip()]


class SentryIssue(BaseModel):
    id: str
    title: str
    level: str
    count: int
    first_seen: str | None = None
    last_seen: str
    permalink: str
    project: str
    # Legacy alias kept for any cached frontend bundle still reading `link`.
    link: str


@router.get("/sentry-issues", response_model=list[SentryIssue])
async def sentry_issues(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> list[SentryIssue]:
    """Fetch the 20 most recent unresolved issues from Sentry.

    Graceful degradation: if SENTRY_AUTH_TOKEN / SENTRY_ORG aren't set,
    returns an empty list with HTTP 200 so the frontend can show
    "No recent issues" instead of an error.
    """
    if not settings.sentry_auth_token or not settings.sentry_org:
        logger.debug("Sentry not configured (no token or org) — returning []")
        return []

    org = settings.sentry_org
    projects = _resolve_sentry_projects()
    headers = {"Authorization": f"Bearer {settings.sentry_auth_token}"}
    all_issues: list[SentryIssue] = []

    async with httpx.AsyncClient(timeout=10) as client:
        for project in projects:
            url = f"https://sentry.io/api/0/projects/{org}/{project}/issues/"
            try:
                resp = await client.get(
                    url,
                    headers=headers,
                    params={"query": "is:unresolved", "sort": "date", "limit": 20},
                )
                resp.raise_for_status()
                for issue in resp.json():
                    permalink = issue.get("permalink", "")
                    all_issues.append(SentryIssue(
                        id=issue["id"],
                        title=issue["title"],
                        level=issue["level"],
                        count=int(issue["count"]),
                        first_seen=issue.get("firstSeen"),
                        last_seen=issue["lastSeen"],
                        permalink=permalink,
                        link=permalink,
                        project=project,
                    ))
            except Exception as exc:
                logger.warning("Sentry fetch failed for %s: %s", project, exc)

    all_issues.sort(key=lambda i: i.last_seen, reverse=True)
    return all_issues[:20]


# ── Chat export ──────────────────────────────────────────────────────────────


@router.get("/export-chats/{user_id}")
async def export_chats(
    user_id: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> JSONResponse:
    """Export all conversations and messages for a user as JSON."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        user_row = await conn.fetchrow(
            "SELECT email, full_name, role FROM users WHERE id = $1", user_id,
        )
        if not user_row:
            raise HTTPException(status_code=404, detail="User not found")

        conv_rows = await conn.fetch(
            """
            SELECT c.id, c.title, c.created_at, v.name AS vessel_name
            FROM conversations c
            LEFT JOIN vessels v ON v.id = c.vessel_id
            WHERE c.user_id = $1
            ORDER BY c.created_at DESC
            """,
            user_id,
        )

        conversations: list[dict[str, Any]] = []
        for conv in conv_rows:
            msg_rows = await conn.fetch(
                """
                SELECT role, content, model_used, tokens_used,
                       cited_regulation_ids, created_at
                FROM messages
                WHERE conversation_id = $1
                ORDER BY created_at ASC
                """,
                conv["id"],
            )

            messages: list[dict[str, Any]] = []
            for msg in msg_rows:
                cited: list[str] = []
                reg_ids = list(msg["cited_regulation_ids"] or [])
                if reg_ids:
                    reg_rows = await conn.fetch(
                        "SELECT section_number FROM regulations WHERE id = ANY($1::uuid[])",
                        reg_ids,
                    )
                    cited = [r["section_number"] for r in reg_rows]

                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                    "created_at": msg["created_at"].isoformat() if msg["created_at"] else None,
                    "model_used": msg["model_used"],
                    "tokens_used": msg["tokens_used"],
                    "cited_regulations": cited,
                })

            conversations.append({
                "id": str(conv["id"]),
                "title": conv["title"],
                "vessel_name": conv["vessel_name"],
                "created_at": conv["created_at"].isoformat() if conv["created_at"] else None,
                "messages": messages,
            })

    return JSONResponse({
        "user": {
            "email": user_row["email"],
            "full_name": user_row["full_name"],
            "role": user_row["role"],
        },
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "conversations": conversations,
    })


# ── Analytics endpoints ─────────────────────────────────────────────────────


class TopTopic(BaseModel):
    topic: str
    conversation_count: int
    last_asked: str


@router.get("/analytics/top-topics", response_model=list[TopTopic])
async def top_topics(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> list[TopTopic]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT c.title AS topic, COUNT(*) AS conversation_count,
               MAX(c.created_at) AS last_asked
        FROM conversations c
        JOIN users u ON c.user_id = u.id
        WHERE c.title IS NOT NULL
          AND ($1 = FALSE OR u.is_internal IS NOT TRUE)
        GROUP BY c.title
        ORDER BY conversation_count DESC
        LIMIT 20
        """,
        exclude_internal,
    )
    return [
        TopTopic(
            topic=r["topic"],
            conversation_count=r["conversation_count"],
            last_asked=r["last_asked"].isoformat() if r["last_asked"] else "",
        )
        for r in rows
    ]


class TopCitation(BaseModel):
    source: str
    section_number: str
    section_title: str | None
    cite_count: int


@router.get("/analytics/top-citations", response_model=list[TopCitation])
async def top_citations(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> list[TopCitation]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT r.source, r.section_number, r.section_title, COUNT(*) AS cite_count
        FROM messages m
        CROSS JOIN LATERAL unnest(m.cited_regulation_ids) AS reg_id
        JOIN regulations r ON r.id = reg_id
        JOIN conversations c ON m.conversation_id = c.id
        JOIN users u ON c.user_id = u.id
        WHERE m.role = 'assistant'
          AND m.cited_regulation_ids IS NOT NULL
          AND ($1 = FALSE OR u.is_internal IS NOT TRUE)
        GROUP BY r.source, r.section_number, r.section_title
        ORDER BY cite_count DESC
        LIMIT 20
        """,
        exclude_internal,
    )
    return [
        TopCitation(
            source=r["source"],
            section_number=r["section_number"],
            section_title=r["section_title"],
            cite_count=r["cite_count"],
        )
        for r in rows
    ]


class VesselTypeUsage(BaseModel):
    vessel_type: str
    message_count: int
    user_count: int


@router.get("/analytics/usage-by-vessel-type", response_model=list[VesselTypeUsage])
async def usage_by_vessel_type(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> list[VesselTypeUsage]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT v.vessel_type, COUNT(m.id) AS message_count,
               COUNT(DISTINCT c.user_id) AS user_count
        FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        JOIN vessels v ON c.vessel_id = v.id
        JOIN users u ON c.user_id = u.id
        WHERE m.role = 'user'
          AND ($1 = FALSE OR u.is_internal IS NOT TRUE)
        GROUP BY v.vessel_type
        ORDER BY message_count DESC
        """,
        exclude_internal,
    )
    return [
        VesselTypeUsage(
            vessel_type=r["vessel_type"],
            message_count=r["message_count"],
            user_count=r["user_count"],
        )
        for r in rows
    ]


class DayMessageCount(BaseModel):
    day: str
    message_count: int


@router.get("/analytics/messages-per-day", response_model=list[DayMessageCount])
async def messages_per_day(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> list[DayMessageCount]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT DATE(m.created_at) AS day, COUNT(*) AS message_count
        FROM messages m
        JOIN conversations c ON m.conversation_id = c.id
        JOIN users u ON c.user_id = u.id
        WHERE m.created_at > NOW() - INTERVAL '30 days'
          AND m.role = 'user'
          AND ($1 = FALSE OR u.is_internal IS NOT TRUE)
        GROUP BY DATE(m.created_at)
        ORDER BY day
        """,
        exclude_internal,
    )
    return [
        DayMessageCount(
            day=r["day"].isoformat(),
            message_count=r["message_count"],
        )
        for r in rows
    ]


# ── Support tickets ──────────────────────────────────────────────────────────


class SupportTicket(BaseModel):
    id: str
    user_id: str
    user_email: str
    user_name: str | None
    subject: str
    message: str
    status: str
    admin_reply: str | None
    replied_at: str | None
    created_at: str


@router.get("/support-tickets", response_model=list[SupportTicket])
async def list_support_tickets(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    status_filter: str = Query(default="all", alias="status"),
) -> list[SupportTicket]:
    pool = await get_pool()
    if status_filter == "all":
        rows = await pool.fetch(
            "SELECT * FROM support_tickets ORDER BY created_at DESC LIMIT 100"
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM support_tickets WHERE status = $1 ORDER BY created_at DESC LIMIT 100",
            status_filter,
        )
    return [
        SupportTicket(
            id=str(r["id"]),
            user_id=str(r["user_id"]),
            user_email=r["user_email"],
            user_name=r["user_name"],
            subject=r["subject"],
            message=r["message"],
            status=r["status"],
            admin_reply=r["admin_reply"],
            replied_at=r["replied_at"].isoformat() if r["replied_at"] else None,
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
        )
        for r in rows
    ]


class AdminReplyBody(BaseModel):
    reply: str


@router.post("/support-tickets/{ticket_id}/reply", response_model=AdminActionResult)
async def reply_to_ticket(
    ticket_id: str,
    body: AdminReplyBody,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> AdminActionResult:
    if not body.reply.strip():
        raise HTTPException(status_code=422, detail="Reply text is required")

    pool = await get_pool()
    try:
        ticket_uuid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ticket id")

    ticket = await pool.fetchrow(
        "SELECT * FROM support_tickets WHERE id = $1",
        ticket_uuid,
    )
    if not ticket:
        raise HTTPException(status_code=404, detail="Ticket not found")

    from app.email import send_support_reply_email

    try:
        await send_support_reply_email(
            to_email=ticket["user_email"],
            user_name=ticket["user_name"] or "Mariner",
            original_subject=ticket["subject"],
            reply_text=body.reply,
            original_message=ticket["message"],
        )
    except Exception as exc:
        logger.error("Support reply email failed for ticket %s: %s", ticket_id, exc)
        raise HTTPException(status_code=502, detail="Failed to send reply email")

    await pool.execute(
        """
        UPDATE support_tickets
        SET status = 'replied', admin_reply = $1, replied_at = NOW()
        WHERE id = $2
        """,
        body.reply,
        ticket_uuid,
    )
    logger.info("Admin %s replied to ticket %s", admin.email, ticket_id)
    return AdminActionResult(ok=True)


@router.post("/support-tickets/{ticket_id}/close", response_model=AdminActionResult)
async def close_ticket(
    ticket_id: str,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> AdminActionResult:
    pool = await get_pool()
    try:
        ticket_uuid = uuid.UUID(ticket_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ticket id")

    result = await pool.execute(
        "UPDATE support_tickets SET status = 'closed' WHERE id = $1",
        ticket_uuid,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="Ticket not found")
    logger.info("Admin %s closed ticket %s", admin.email, ticket_id)
    return AdminActionResult(ok=True)

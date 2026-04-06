"""Admin dashboard endpoints — stats, user list, model usage, pilot reset, email testing, Sentry, export."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

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
READONLY_ADMIN_EMAILS: set[str] = {"kdmarchal@gmail.com"}


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


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> AdminStats:
    pool = await get_pool()
    # When filtering, exclude users where is_internal = TRUE and their data
    uf = " AND u.is_internal = FALSE" if exclude_internal else ""
    muf = (
        " AND m.conversation_id IN (SELECT c2.id FROM conversations c2 JOIN users u2 ON u2.id = c2.user_id WHERE u2.is_internal = FALSE)"
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
            f"SELECT COUNT(*) FROM messages m{muf}"
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
    exclude_internal: bool = Query(default=False),
) -> list[AdminUser]:
    pool = await get_pool()
    where = "WHERE is_internal = FALSE" if exclude_internal else ""
    rows = await pool.fetch(
        f"""
        SELECT id, email, full_name, role, subscription_tier,
               subscription_status, message_count, trial_ends_at, created_at, is_admin
        FROM users
        {where}
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
            WHERE u.is_internal = FALSE
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


# ── Sentry issues ────────────────────────────────────────────────────────────

SENTRY_PROJECTS = ["regknots-api", "regknots-web"]


class SentryIssue(BaseModel):
    id: str
    title: str
    level: str
    count: int
    last_seen: str
    link: str
    project: str


@router.get("/sentry-issues", response_model=list[SentryIssue])
async def sentry_issues(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> list[SentryIssue]:
    """Fetch the 10 most recent unresolved issues from Sentry."""
    if not settings.sentry_auth_token or not settings.sentry_org:
        return []

    org = settings.sentry_org
    headers = {"Authorization": f"Bearer {settings.sentry_auth_token}"}
    all_issues: list[SentryIssue] = []

    async with httpx.AsyncClient(timeout=10) as client:
        for project in SENTRY_PROJECTS:
            url = f"https://sentry.io/api/0/projects/{org}/{project}/issues/"
            try:
                resp = await client.get(
                    url,
                    headers=headers,
                    params={"query": "is:unresolved", "sort": "date", "limit": 10},
                )
                resp.raise_for_status()
                for issue in resp.json():
                    all_issues.append(SentryIssue(
                        id=issue["id"],
                        title=issue["title"],
                        level=issue["level"],
                        count=int(issue["count"]),
                        last_seen=issue["lastSeen"],
                        link=issue["permalink"],
                        project=project,
                    ))
            except Exception as exc:
                logger.warning("Sentry fetch failed for %s: %s", project, exc)

    all_issues.sort(key=lambda i: i.last_seen, reverse=True)
    return all_issues[:10]


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
          AND ($1 = FALSE OR u.is_internal = FALSE)
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
        FROM messages m, unnest(m.cited_regulation_ids) AS reg_id
        JOIN regulations r ON r.id = reg_id
        JOIN conversations c ON m.conversation_id = c.id
        JOIN users u ON c.user_id = u.id
        WHERE m.role = 'assistant'
          AND ($1 = FALSE OR u.is_internal = FALSE)
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
          AND ($1 = FALSE OR u.is_internal = FALSE)
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
          AND ($1 = FALSE OR u.is_internal = FALSE)
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

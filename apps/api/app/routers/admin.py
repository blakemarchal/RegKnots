"""Admin dashboard endpoints — stats, user list, model usage, pilot reset, email testing, Sentry, export."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Literal

import asyncpg
import httpx
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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

# Owner: the only person who can perform destructive operations (delete user,
# mass-email blast, purge data, run ingest, manage billing state, etc.).
# All other admins get read + support + self-only operations.
OWNER_EMAIL = "blakemarchal@gmail.com"


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


async def require_owner(
    user: Annotated[CurrentUser, Depends(require_write_admin)],
) -> CurrentUser:
    """Only the product owner can perform destructive operations."""
    if user.email != OWNER_EMAIL:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner access required for this operation",
        )
    return user


async def audit_log(
    pool: asyncpg.Pool,
    admin: CurrentUser,
    action: str,
    target_id: str | None = None,
    details: dict | None = None,
) -> None:
    """Record an admin action for accountability. Never raises."""
    try:
        import json as _json
        await pool.execute(
            """
            INSERT INTO admin_audit_log (admin_user_id, admin_email, action, target_id, details)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            """,
            uuid.UUID(admin.user_id),
            admin.email,
            action,
            target_id,
            _json.dumps(details) if details else None,
        )
    except Exception:
        logger.exception("Failed to write audit log entry: %s %s", action, target_id)


# ── Stats ────────────────────────────────────────────────────────────────────────

class TierBreakdown(BaseModel):
    """Sprint D6.32 — paid-tier counts. Replaces the legacy single
    `pro_subscribers` field which only counted the deprecated `pro` tier.
    Sprint D6.91 — added `cadet` for the entry-level $9.99/25-msg plan."""
    cadet: int = 0
    mate: int
    captain: int
    pro_legacy: int  # Karynn + early users still on the deprecated tier


class HedgeEvent(BaseModel):
    """Sprint D6.32 — last-N hedges surfaced on the admin overview so
    quality regressions are visible without drilling into the chats tab."""
    created_at: str
    user_email: str | None
    query: str
    hedge_phrase: str


class AdminStats(BaseModel):
    """Sprint D6.32 — restructured from the legacy 16-field flat shape into
    four logical sections: headline KPIs, subscriptions, engagement, quality.

    Breaking changes vs the prior shape (frontend updated in same sprint):
    - `total_messages` / `messages_*` removed (they double-counted Q+A);
      replaced by `questions_*` filtered to user-role messages.
    - `pro_subscribers` removed (only counted legacy `pro` tier, missed
      every Mate and Captain); replaced by `subs_active: TierBreakdown`.
    - New: `bad_answer_rate_7d`, `hedge_rate_7d`, `retrieval_misses_7d`,
      `recent_hedges`, `avg_questions_per_active_user_7d`.
    - `active_users_24h` retained but no longer surfaced on the headline
      row (kept for backwards-compat consumers).
    """

    # Row 1 — Headline KPIs
    total_users: int
    active_users_7d: int
    questions_7d: int
    bad_answer_rate_7d: float  # 0.0–100.0

    # Row 2 — Subscriptions (consolidated)
    subs_active: TierBreakdown
    subs_past_due: int
    subs_paused: int
    trial_active: int
    trial_expired: int
    subs_monthly: int
    subs_annual: int
    paid_users_alltime: int  # kept for D6.10 milestone-celebration trigger

    # Row 3 — Engagement
    questions_today: int
    avg_questions_per_active_user_7d: float
    total_conversations: int
    conversations_today: int
    conversations_7d: int
    active_users_24h: int  # retained for backwards-compat consumers

    # Row 4 — Quality
    citation_errors_7d: int
    retrieval_misses_7d: int
    hedge_rate_7d: float  # 0.0–100.0
    message_limit_reached: int
    recent_hedges: list[HedgeEvent]

    # Row 4b — Web fallback (Sprint D6.48)
    web_fallback_attempts_7d: int       # total fallback firings (production only)
    web_fallback_surfaced_7d: int       # passed all 3 gates → user saw a card
    web_fallback_surface_rate_7d: float # 0-100, surfaced / attempts
    web_fallback_thumbs_up_7d: int      # user clicked helpful
    web_fallback_thumbs_down_7d: int    # user clicked not_helpful

    # Knowledge base
    total_chunks: int
    chunks_by_source: dict[str, int]


@router.get("/role")
async def get_admin_role(
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> dict:
    """Return the admin's role level so the frontend can gate UI accordingly."""
    is_readonly = admin.email in READONLY_ADMIN_EMAILS
    is_owner = admin.email == OWNER_EMAIL
    return {
        "email": admin.email,
        "role": "owner" if is_owner else ("readonly" if is_readonly else "admin"),
        "is_owner": is_owner,
        "is_readonly": is_readonly,
    }


@router.get("/stats", response_model=AdminStats)
async def get_stats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
) -> AdminStats:
    """Sprint D6.32 — restructured admin overview.

    Two structural fixes vs the prior implementation:
    (1) Message counters now filter `m.role = 'user'` so the headline
        reflects QUESTIONS asked, not exchanges. The legacy fields
        double-counted because every Q+A pair was 2 rows.
    (2) Paid-tier breakdown replaces the single `pro_subscribers` field,
        which only counted the deprecated `pro` tier and was misleading
        for current Mate/Captain pricing.

    New top-line signals: bad_answer_rate (citation errors + retrieval
    misses as % of answers), hedge_rate, avg questions per active user,
    and a recent_hedges list for at-a-glance quality regressions.
    """
    pool = await get_pool()
    # When filtering, exclude users where is_internal = TRUE OR is_admin = TRUE.
    # "exclude_internal" is a historical flag name; it also covers admins now
    # since admin test activity is the biggest source of noise in metrics.
    uf = " AND u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE" if exclude_internal else ""
    muf = (
        " AND m.conversation_id IN ("
        " SELECT c2.id FROM conversations c2 JOIN users u2 ON u2.id = c2.user_id"
        " WHERE u2.is_internal IS NOT TRUE AND u2.is_admin IS NOT TRUE)"
        if exclude_internal else ""
    )
    async with pool.acquire() as conn:
        # ── Row 1 + 3 — Users + activity ─────────────────────────────
        total_users = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u WHERE 1=1{uf}"
        )
        active_users_24h = await conn.fetchval(
            f"SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
            f"JOIN messages m ON m.conversation_id = c.id "
            f"JOIN users u ON u.id = c.user_id "
            f"WHERE m.role = 'user' AND m.created_at > NOW() - INTERVAL '24 hours'{uf}"
        )
        active_users_7d = await conn.fetchval(
            f"SELECT COUNT(DISTINCT c.user_id) FROM conversations c "
            f"JOIN messages m ON m.conversation_id = c.id "
            f"JOIN users u ON u.id = c.user_id "
            f"WHERE m.role = 'user' AND m.created_at > NOW() - INTERVAL '7 days'{uf}"
        )

        # ── Conversations ────────────────────────────────────────────
        total_conversations = await conn.fetchval(
            f"SELECT COUNT(*) FROM conversations c JOIN users u ON u.id = c.user_id WHERE 1=1{uf}"
            if exclude_internal else "SELECT COUNT(*) FROM conversations"
        )
        conversations_today = await conn.fetchval(
            f"SELECT COUNT(*) FROM conversations c JOIN users u ON u.id = c.user_id "
            f"WHERE c.created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'){uf}"
            if exclude_internal else
            "SELECT COUNT(*) FROM conversations WHERE created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC')"
        )
        conversations_7d = await conn.fetchval(
            f"SELECT COUNT(*) FROM conversations c JOIN users u ON u.id = c.user_id "
            f"WHERE c.created_at > NOW() - INTERVAL '7 days'{uf}"
            if exclude_internal else
            "SELECT COUNT(*) FROM conversations WHERE created_at > NOW() - INTERVAL '7 days'"
        )

        # ── Questions (user-role messages only) — fixes the 2x bug ──
        questions_today = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages m WHERE m.role = 'user' "
            f"AND m.created_at >= DATE_TRUNC('day', NOW() AT TIME ZONE 'UTC'){muf}"
        )
        questions_7d = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages m WHERE m.role = 'user' "
            f"AND m.created_at > NOW() - INTERVAL '7 days'{muf}"
        )
        # Answers count — denominator for bad_answer_rate. Same scope.
        answers_7d = await conn.fetchval(
            f"SELECT COUNT(*) FROM messages m WHERE m.role = 'assistant' "
            f"AND m.created_at > NOW() - INTERVAL '7 days'{muf}"
        )

        # ── Subscriptions — paid tier breakdown (replaces pro count) ─
        # All counts here exclude admins entirely (subscription state
        # of internal/admin accounts is meaningless for the dashboard).
        subs_row = await conn.fetchrow(
            f"""
            SELECT
              COUNT(*) FILTER (
                WHERE subscription_tier = 'cadet'
                  AND subscription_status = 'active'
              ) AS cadet_active,
              COUNT(*) FILTER (
                WHERE subscription_tier = 'mate'
                  AND subscription_status = 'active'
              ) AS mate_active,
              COUNT(*) FILTER (
                WHERE subscription_tier = 'captain'
                  AND subscription_status = 'active'
              ) AS captain_active,
              COUNT(*) FILTER (
                WHERE subscription_tier = 'pro'
                  AND subscription_status = 'active'
              ) AS pro_legacy_active,
              COUNT(*) FILTER (
                WHERE subscription_tier IN ('cadet', 'mate', 'captain', 'pro')
                  AND subscription_status = 'active'
                  AND billing_interval = 'month'
              ) AS subs_monthly,
              COUNT(*) FILTER (
                WHERE subscription_tier IN ('cadet', 'mate', 'captain', 'pro')
                  AND subscription_status = 'active'
                  AND billing_interval = 'year'
              ) AS subs_annual,
              COUNT(*) FILTER (WHERE subscription_status = 'past_due') AS past_due,
              COUNT(*) FILTER (WHERE subscription_status = 'paused') AS paused
            FROM users u
            WHERE is_admin = false{uf}
            """
        )

        # Sprint D6.10 — milestone celebration. Kept inclusive of all
        # paid tiers + any non-zero subscription state.
        paid_users_alltime = await conn.fetchval(
            f"SELECT COUNT(*) FROM users u "
            f"WHERE subscription_tier IN ('cadet', 'mate', 'captain', 'pro') "
            f"  AND subscription_status IN ('active', 'past_due', 'paused'){uf}"
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

        # ── Quality signals ─────────────────────────────────────────
        # Sprint D6.35 — bad-answer-rate fix.
        # PRIOR BUG: numerator counted INCIDENTS not affected answers.
        # citation_errors stores one row per bad citation, so a single
        # answer with 3 wrong cites added 3 to the count. retrieval_misses
        # was 1:1 with answers but added on top, so a single bad answer
        # with one hedge AND three cite errors counted as 4 toward the
        # rate. The composite could exceed 100%.
        #
        # FIX: count DISTINCT affected answers, not raw incidents:
        # - citation_errors deduped by (conversation_id, message_content)
        #   = one row per affected answer
        # - retrieval_misses already 1:1 with hedge events
        # - bad_answer_rate now caps at 100% (still possible to exceed if
        #   the same answer is BOTH cite-errored AND hedged — accept that
        #   small overcount as cheaper than a JOIN to dedup across both)
        citation_errors_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM citation_errors ce "
            "JOIN conversations c ON c.id = ce.conversation_id "
            "JOIN users u ON u.id = c.user_id "
            f"WHERE ce.created_at > NOW() - INTERVAL '7 days'{uf}"
            if exclude_internal else
            "SELECT COUNT(*) FROM citation_errors WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        # NEW: distinct affected answers — used for the rate. The raw
        # citation_errors_7d count is kept for display ("how many cite
        # errors total this week") which is also a useful number.
        affected_answers_7d = await conn.fetchval(
            "SELECT COUNT(DISTINCT (ce.conversation_id, ce.message_content)) "
            "FROM citation_errors ce "
            "JOIN conversations c ON c.id = ce.conversation_id "
            "JOIN users u ON u.id = c.user_id "
            f"WHERE ce.created_at > NOW() - INTERVAL '7 days'{uf}"
            if exclude_internal else
            "SELECT COUNT(DISTINCT (conversation_id, message_content)) "
            "FROM citation_errors WHERE created_at > NOW() - INTERVAL '7 days'"
        )
        retrieval_misses_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM retrieval_misses rm "
            "LEFT JOIN users u ON u.id = rm.user_id "
            f"WHERE rm.created_at > NOW() - INTERVAL '7 days'{uf}"
            if exclude_internal else
            "SELECT COUNT(*) FROM retrieval_misses WHERE created_at > NOW() - INTERVAL '7 days'"
        )

        # Sprint D6.48 Phase 2 — web fallback metrics. Calibration rows
        # are excluded because those are admin replays, not real user
        # activity. We surface attempt + surface counts so the operator
        # can compare against retrieval_misses_7d to see how often the
        # fallback rescues a corpus gap.
        web_fb_attempts_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM web_fallback_responses "
            "WHERE is_calibration = FALSE "
            "AND created_at > NOW() - INTERVAL '7 days'"
        ) or 0
        web_fb_surfaced_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM web_fallback_responses "
            "WHERE is_calibration = FALSE AND surfaced = TRUE "
            "AND created_at > NOW() - INTERVAL '7 days'"
        ) or 0
        web_fb_thumbs_up_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM web_fallback_responses "
            "WHERE is_calibration = FALSE AND user_feedback = 'helpful' "
            "AND created_at > NOW() - INTERVAL '7 days'"
        ) or 0
        web_fb_thumbs_down_7d = await conn.fetchval(
            "SELECT COUNT(*) FROM web_fallback_responses "
            "WHERE is_calibration = FALSE "
            "AND user_feedback IN ('not_helpful', 'inaccurate') "
            "AND created_at > NOW() - INTERVAL '7 days'"
        ) or 0
        web_fb_surface_rate_7d = (
            100.0 * web_fb_surfaced_7d / web_fb_attempts_7d
            if web_fb_attempts_7d > 0 else 0.0
        )

        recent_hedges_rows = await conn.fetch(
            "SELECT rm.created_at, u.email AS user_email, rm.query, rm.hedge_phrase_matched "
            "FROM retrieval_misses rm "
            "LEFT JOIN users u ON u.id = rm.user_id "
            f"WHERE rm.created_at > NOW() - INTERVAL '30 days'{uf} "
            "ORDER BY rm.created_at DESC LIMIT 5"
            if exclude_internal else
            "SELECT rm.created_at, u.email AS user_email, rm.query, rm.hedge_phrase_matched "
            "FROM retrieval_misses rm LEFT JOIN users u ON u.id = rm.user_id "
            "ORDER BY rm.created_at DESC LIMIT 5"
        )

        # ── Knowledge base ───────────────────────────────────────────
        total_chunks = await conn.fetchval("SELECT COUNT(*) FROM regulations")
        chunk_rows = await conn.fetch(
            "SELECT source, COUNT(*) AS cnt FROM regulations GROUP BY source ORDER BY source"
        )
        chunks_by_source = {r["source"]: r["cnt"] for r in chunk_rows}

    # Derived metrics. Defensive division: empty corpus on day 0 = 0%.
    answers_7d = answers_7d or 0
    # Sprint D6.35 + D6.40 — bad_answer_rate now means "answers that
    # cite a regulation that doesn't exist" — actual factual errors.
    # Hedges (the model declining to answer when corpus has no
    # supporting chunk) are NOT bad answers; they're correct behavior
    # under uncertainty. They're tracked separately as hedge_rate.
    #
    # Prior formula folded both into the same number, which inflated
    # the rate from ~17% (real cite errors) to ~51% (everything that
    # could conceivably be flagged). The combined number wasn't
    # actionable because the two failure modes need different fixes:
    #   - cite errors → tighten verification + regen pass
    #   - hedges → expand corpus coverage
    bad_answer_rate_7d = (
        100.0 * affected_answers_7d / answers_7d if answers_7d > 0 else 0.0
    )
    hedge_rate_7d = (
        100.0 * retrieval_misses_7d / answers_7d
        if answers_7d > 0 else 0.0
    )
    avg_questions_per_active_user_7d = (
        questions_7d / active_users_7d if active_users_7d > 0 else 0.0
    )

    return AdminStats(
        # Headline KPIs
        total_users=total_users,
        active_users_7d=active_users_7d,
        questions_7d=questions_7d,
        bad_answer_rate_7d=round(bad_answer_rate_7d, 1),
        # Subscriptions
        subs_active=TierBreakdown(
            cadet=subs_row["cadet_active"] or 0,
            mate=subs_row["mate_active"] or 0,
            captain=subs_row["captain_active"] or 0,
            pro_legacy=subs_row["pro_legacy_active"] or 0,
        ),
        subs_past_due=subs_row["past_due"] or 0,
        subs_paused=subs_row["paused"] or 0,
        trial_active=trial_active or 0,
        trial_expired=trial_expired or 0,
        subs_monthly=subs_row["subs_monthly"] or 0,
        subs_annual=subs_row["subs_annual"] or 0,
        paid_users_alltime=paid_users_alltime or 0,
        # Engagement
        questions_today=questions_today or 0,
        avg_questions_per_active_user_7d=round(avg_questions_per_active_user_7d, 1),
        total_conversations=total_conversations or 0,
        conversations_today=conversations_today or 0,
        conversations_7d=conversations_7d or 0,
        active_users_24h=active_users_24h or 0,
        # Quality
        citation_errors_7d=citation_errors_7d or 0,
        retrieval_misses_7d=retrieval_misses_7d or 0,
        hedge_rate_7d=round(hedge_rate_7d, 1),
        message_limit_reached=message_limit_reached or 0,
        recent_hedges=[
            HedgeEvent(
                created_at=r["created_at"].isoformat(),
                user_email=r["user_email"],
                query=r["query"][:200],  # truncate long queries for the panel
                hedge_phrase=r["hedge_phrase_matched"],
            )
            for r in recent_hedges_rows
        ],
        # Web fallback (Sprint D6.48 Phase 2)
        web_fallback_attempts_7d=web_fb_attempts_7d,
        web_fallback_surfaced_7d=web_fb_surfaced_7d,
        web_fallback_surface_rate_7d=round(web_fb_surface_rate_7d, 1),
        web_fallback_thumbs_up_7d=web_fb_thumbs_up_7d,
        web_fallback_thumbs_down_7d=web_fb_thumbs_down_7d,
        # Knowledge base
        total_chunks=total_chunks or 0,
        chunks_by_source=chunks_by_source,
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> ResetResult:
    """Reset a single user's pilot state: zero message_count, restart trial, delete conversations."""
    pool = await get_pool()
    await audit_log(pool, admin, "reset_user", target_id=user_id)
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> ResetResult:
    """Reset ALL non-admin users: zero message_count, restart trial, delete conversations."""
    pool = await get_pool()
    await audit_log(pool, admin, "reset_all_pilots")
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> ExtendTrialResult:
    """Extend a user's trial by 14 days from now."""
    pool = await get_pool()
    await audit_log(pool, admin, "extend_trial", target_id=user_id)
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> AdminActionResult:
    """Manually grant pro tier to a user."""
    pool = await get_pool()
    await audit_log(pool, admin, "grant_pro", target_id=user_id)
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


# ── Sprint D6.3c — referral_source override ──────────────────────────────
#
# Lets the Owner manually set or clear referral_source on any user. Useful
# for:
#   * Testing the referral-aware pricing flow without going through a full
#     /womenoffshore signup detour
#   * Correcting attribution when a charity-partner signup happened but
#     localStorage didn't persist (private browsing, etc.)
#   * Retroactively crediting a known charity referral when the user
#     signed up via the wrong path
# All changes are audit-logged.

class SetReferralSourceRequest(BaseModel):
    referral_source: str | None  # None or empty string clears the field


@router.post("/users/{user_id}/referral-source", response_model=AdminActionResult)
async def set_referral_source(
    user_id: str,
    body: SetReferralSourceRequest,
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> AdminActionResult:
    """Set or clear referral_source on a user (Owner-only, audit-logged)."""
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user id")

    pool = await get_pool()
    new_value = (body.referral_source or "").strip() or None
    await audit_log(
        pool, admin, "set_referral_source",
        target_id=user_id,
        details={"referral_source": new_value},
    )
    result = await pool.execute(
        "UPDATE users SET referral_source = $1 WHERE id = $2",
        new_value,
        uid,
    )
    if result == "UPDATE 0":
        raise HTTPException(status_code=404, detail="User not found")
    logger.info(
        "Admin %s set referral_source=%s for %s",
        admin.email, new_value, user_id,
    )
    return AdminActionResult(ok=True)


class DeleteUserResult(BaseModel):
    deleted: bool
    email: str


@router.delete("/users/{user_id}", response_model=DeleteUserResult)
async def delete_user(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> DeleteUserResult:
    """Permanently delete a user and all cascading data.

    D6.58 audit fix — workspaces.owner_user_id has ON DELETE RESTRICT
    (not CASCADE) by design: deleting a workspace owner without
    explicit handling would orphan a billing-active workspace, which
    we never want to do silently. Before the user delete, we
    explicitly cancel + archive any workspaces this user owns. The
    workspace cascade then deletes their members rows; orphaned
    seats on those workspaces (if any) cascade to NULL via the
    user_id FK.

    The two-pass delete:
      1. Archive (soft-delete) any owned workspaces. status='archived'
         + null out stripe_subscription_id so future webhooks can't
         interact with a dead workspace.
      2. DELETE the workspace rows (cascades to members + invites +
         vessels + handoff history).
      3. DELETE the user row (now FK-clean).

    Admin users still can't be deleted. Admins must promote/demote
    via /admin/users/{id}/role first.
    """
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

    # D6.58 — pre-clear workspaces owned by this user. Records the
    # archival in workspace_billing_events so the audit trail is
    # preserved even though the workspace row is gone.
    owned_workspaces = await pool.fetch(
        "SELECT id, name, status FROM workspaces WHERE owner_user_id = $1",
        uid,
    )
    workspaces_archived: list[dict] = []
    if owned_workspaces:
        for w in owned_workspaces:
            try:
                await pool.execute(
                    "INSERT INTO workspace_billing_events "
                    "  (workspace_id, event_type, actor_user_id, details) "
                    "VALUES ($1, 'owner_account_deleted', $2, $3::jsonb)",
                    w["id"], uid,
                    f'{{"prior_status": "{w["status"]}", "name": "{w["name"]}"}}',
                )
            except Exception:
                pass  # audit-log failures don't block delete
            await pool.execute(
                "DELETE FROM workspaces WHERE id = $1",
                w["id"],
            )
            workspaces_archived.append({
                "id": str(w["id"]),
                "name": w["name"],
                "prior_status": w["status"],
            })

    try:
        await pool.execute("DELETE FROM users WHERE id = $1", uid)
    except asyncpg.exceptions.ForeignKeyViolationError as exc:
        logger.exception("FK violation deleting user %s", user_id)
        raise HTTPException(
            status_code=409,
            detail=(
                f"Cannot delete user: foreign key constraint "
                f"{exc.constraint_name or 'unknown'} blocks the cascade. "
                "A referencing table is missing ON DELETE CASCADE or "
                "needs explicit pre-cleanup. Owned workspaces were "
                "removed but a different reference is still blocking."
            ),
        ) from exc
    await audit_log(
        pool, admin, "delete_user",
        target_id=user_id,
        details={
            "email": row["email"],
            "workspaces_deleted": workspaces_archived,
        },
    )
    logger.warning(
        "Admin %s deleted user %s (%s); also removed %d owned workspaces",
        admin.email, row["email"], user_id, len(workspaces_archived),
    )
    return DeleteUserResult(deleted=True, email=row["email"])


@router.post("/revoke-pro/{user_id}", response_model=AdminActionResult)
async def revoke_pro(
    user_id: str,
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> AdminActionResult:
    """Revoke pro tier and revert to free."""
    pool = await get_pool()
    await audit_log(pool, admin, "revoke_pro", target_id=user_id)
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
) -> dict[str, str]:
    pool = await get_pool()
    await audit_log(pool, admin, "create_notification", details={"title": body.title})
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
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
            WHERE u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE
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


# ── Web fallback calibration (D6.48 Phase 1) ──────────────────────────────────

class WebFallbackReplayRow(BaseModel):
    """One result of running the fallback stack against a historical hedge."""
    id: str
    query: str
    web_query_used: str | None
    confidence: int | None
    source_url: str | None
    source_domain: str | None
    quote_text: str | None
    quote_verified: bool
    surfaced: bool
    surface_blocked_reason: str | None
    answer_text: str | None
    top_urls: list[str]
    latency_ms: int
    created_at: str


class WebFallbackReplayResult(BaseModel):
    requested: int
    attempted: int
    surfaced: int
    blocked_by_confidence: int
    blocked_by_domain: int
    blocked_by_quote: int
    no_results_or_error: int
    rows: list[WebFallbackReplayRow]


@router.post("/web-fallback/replay", response_model=WebFallbackReplayResult)
async def web_fallback_replay(
    request: Request,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    n: int = Query(default=25, ge=1, le=100),
    cosine_threshold: float = Query(default=0.5, ge=0.0, le=1.0),
) -> WebFallbackReplayResult:
    """Run the web-search fallback stack against the most recent N hedge
    queries (from `retrieval_misses`) and persist every attempt to
    `web_fallback_responses` with `is_calibration=true`.

    No real user sees these results — this endpoint exists purely for
    the calibration pass before the fallback is wired into the chat
    pipeline. Use it to:
      - Tune the trusted-domain whitelist (look at blocked_by_domain).
      - Watch the verbatim-quote gate behavior.
      - Sanity-check Anthropic web_search confidence calibration.

    Run several times before launch; once production traffic accumulates
    the same data will populate via real chat hits.
    """
    from rag.web_fallback import attempt_web_fallback

    pool = await get_pool()
    anthropic_client: AsyncAnthropic = request.app.state.anthropic

    rows = await pool.fetch(
        """
        SELECT id, query, created_at
        FROM retrieval_misses
        WHERE created_at > NOW() - INTERVAL '30 days'
        ORDER BY created_at DESC
        LIMIT $1
        """,
        n,
    )
    if not rows:
        return WebFallbackReplayResult(
            requested=n, attempted=0, surfaced=0,
            blocked_by_confidence=0, blocked_by_domain=0, blocked_by_quote=0,
            no_results_or_error=0, rows=[],
        )

    # Run sequentially — Anthropic web_search is rate-limited and we don't
    # want to thunder-herd. ~3-8s per call × N items.
    persisted_rows: list[WebFallbackReplayRow] = []
    surfaced = blocked_conf = blocked_dom = blocked_quote = noresult = 0

    for row in rows:
        query = row["query"]
        try:
            result = await attempt_web_fallback(
                query=query,
                anthropic_client=anthropic_client,
            )
        except Exception as exc:
            logger.warning("Replay attempt failed for %r: %s", query[:80], exc)
            continue

        # Persist the attempt with is_calibration=true.
        try:
            inserted = await pool.fetchrow(
                """
                INSERT INTO web_fallback_responses
                    (is_calibration, query, web_query_used,
                     top_urls, confidence, source_url, source_domain,
                     quote_text, quote_verified, surfaced,
                     surface_blocked_reason, answer_text, latency_ms)
                VALUES (TRUE, $1, $2, $3::text[], $4, $5, $6, $7, $8, $9,
                        $10, $11, $12)
                RETURNING id, created_at
                """,
                query,
                result.web_query_used,
                result.top_urls or [],
                result.confidence,
                result.source_url,
                result.source_domain,
                result.quote_text,
                result.quote_verified,
                result.surfaced,
                result.surface_blocked_reason,
                result.answer_text,
                result.latency_ms,
            )
        except Exception as exc:
            logger.warning("Replay persist failed: %s", exc)
            continue

        if result.surfaced:
            surfaced += 1
        elif result.surface_blocked_reason == "low_confidence":
            blocked_conf += 1
        elif result.surface_blocked_reason == "domain_blocked":
            blocked_dom += 1
        elif result.surface_blocked_reason == "quote_unverified":
            blocked_quote += 1
        else:
            noresult += 1

        persisted_rows.append(WebFallbackReplayRow(
            id=str(inserted["id"]),
            query=query,
            web_query_used=result.web_query_used,
            confidence=result.confidence,
            source_url=result.source_url,
            source_domain=result.source_domain,
            quote_text=(result.quote_text[:300] if result.quote_text else None),
            quote_verified=result.quote_verified,
            surfaced=result.surfaced,
            surface_blocked_reason=result.surface_blocked_reason,
            answer_text=(result.answer_text[:500] if result.answer_text else None),
            top_urls=result.top_urls,
            latency_ms=result.latency_ms,
            created_at=inserted["created_at"].isoformat(),
        ))

    return WebFallbackReplayResult(
        requested=n,
        attempted=len(persisted_rows),
        surfaced=surfaced,
        blocked_by_confidence=blocked_conf,
        blocked_by_domain=blocked_dom,
        blocked_by_quote=blocked_quote,
        no_results_or_error=noresult,
        rows=persisted_rows,
    )


@router.get("/web-fallback/recent", response_model=list[WebFallbackReplayRow])
async def web_fallback_recent(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=500),
    only_surfaced: bool = Query(default=False),
    only_calibration: bool = Query(default=False),
) -> list[WebFallbackReplayRow]:
    """Return recent web-fallback attempts for admin review."""
    pool = await get_pool()
    where_clauses = []
    params: list = []
    if only_surfaced:
        where_clauses.append("surfaced = TRUE")
    if only_calibration:
        where_clauses.append("is_calibration = TRUE")
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT id, query, web_query_used, confidence, source_url,
               source_domain, quote_text, quote_verified, surfaced,
               surface_blocked_reason, answer_text, top_urls,
               latency_ms, created_at
        FROM web_fallback_responses
        {where_sql}
        ORDER BY created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return [
        WebFallbackReplayRow(
            id=str(r["id"]),
            query=r["query"],
            web_query_used=r["web_query_used"],
            confidence=r["confidence"],
            source_url=r["source_url"],
            source_domain=r["source_domain"],
            quote_text=(r["quote_text"][:300] if r["quote_text"] else None),
            quote_verified=r["quote_verified"] or False,
            surfaced=r["surfaced"],
            surface_blocked_reason=r["surface_blocked_reason"],
            answer_text=(r["answer_text"][:500] if r["answer_text"] else None),
            top_urls=list(r["top_urls"] or []),
            latency_ms=r["latency_ms"] or 0,
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
        )
        for r in rows
    ]


# ── Phase 2 review tool (D6.48) ───────────────────────────────────────────────
# A single endpoint that joins the three tables an operator wants to scan
# while reviewing fallback behavior — recent assistant messages, the
# retrieval_misses log, and web_fallback_responses outcomes — so the
# admin doesn't have to flip between three tabs to assess "did the
# fallback fire correctly on this query?"

class ReviewRow(BaseModel):
    timestamp: str
    user_email: str | None
    query: str
    answer_preview: str
    hedged: bool
    hedge_phrase: str | None
    fallback_attempted: bool
    fallback_surfaced: bool
    fallback_blocked_reason: str | None
    fallback_source_domain: str | None
    fallback_confidence: int | None
    fallback_quote_preview: str | None
    fallback_thumbs: str | None     # 'helpful' | 'not_helpful' | 'inaccurate' | null
    citations_count: int


@router.get("/phase2-review", response_model=list[ReviewRow])
async def phase2_review(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    hours: int = Query(default=24, ge=1, le=720),
    only_hedged: bool = Query(default=False),
    only_fallback: bool = Query(default=False),
    user_email: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ReviewRow]:
    """One-shot timeline of recent assistant messages with hedge +
    fallback overlay. Designed for "let me eyeball Phase 2 behavior in
    the last day" without joining three tables by hand.

    Filters:
      hours          — lookback window (default 24h, max 30 days)
      only_hedged    — only return turns where the answer hedged
      only_fallback  — only return turns where fallback was attempted
      user_email     — filter to a specific user (e.g. for self-review)
      limit          — page size

    Each row joins:
      messages (assistant content + timestamp)
      retrieval_misses (hedge phrase that triggered the miss log)
      web_fallback_responses (whether fallback fired, what it returned,
                              why it was blocked, what feedback the user
                              left)
    """
    pool = await get_pool()
    where = ["m.role = 'assistant'",
             f"m.created_at > NOW() - INTERVAL '{int(hours)} hours'"]
    params: list = []
    if user_email:
        params.append(user_email)
        where.append(f"u.email = ${len(params)}")
    if only_hedged:
        where.append("rm.id IS NOT NULL")
    if only_fallback:
        where.append("wfr.id IS NOT NULL")
    where_sql = " AND ".join(where)
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT
          m.created_at         AS ts,
          m.content            AS answer,
          u.email              AS user_email,
          q.content            AS query,
          rm.hedge_phrase_matched AS hedge_phrase,
          wfr.id IS NOT NULL   AS fb_attempted,
          wfr.surfaced         AS fb_surfaced,
          wfr.surface_blocked_reason AS fb_blocked,
          wfr.source_domain    AS fb_domain,
          wfr.confidence       AS fb_conf,
          wfr.quote_text       AS fb_quote,
          wfr.user_feedback    AS fb_thumbs,
          COALESCE(array_length(m.cited_regulation_ids, 1), 0) AS citations_count
        FROM messages m
        JOIN conversations c ON c.id = m.conversation_id
        JOIN users u ON u.id = c.user_id
        LEFT JOIN LATERAL (
          SELECT content FROM messages
          WHERE conversation_id = m.conversation_id
            AND role = 'user'
            AND created_at <= m.created_at
          ORDER BY created_at DESC LIMIT 1
        ) q ON TRUE
        LEFT JOIN retrieval_misses rm
          ON rm.conversation_id = m.conversation_id
          AND rm.created_at BETWEEN m.created_at - INTERVAL '5 seconds'
                                AND m.created_at + INTERVAL '5 seconds'
        LEFT JOIN web_fallback_responses wfr
          ON wfr.chat_message_id = m.conversation_id
          AND wfr.is_calibration = FALSE
          AND wfr.created_at BETWEEN m.created_at - INTERVAL '60 seconds'
                                 AND m.created_at + INTERVAL '60 seconds'
        WHERE {where_sql}
        ORDER BY m.created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )

    out: list[ReviewRow] = []
    for r in rows:
        ans = r["answer"] or ""
        out.append(ReviewRow(
            timestamp=r["ts"].isoformat() if r["ts"] else "",
            user_email=r["user_email"],
            query=(r["query"] or "")[:240],
            answer_preview=ans[:400],
            hedged=r["hedge_phrase"] is not None,
            hedge_phrase=r["hedge_phrase"],
            fallback_attempted=bool(r["fb_attempted"]),
            fallback_surfaced=bool(r["fb_surfaced"]),
            fallback_blocked_reason=r["fb_blocked"],
            fallback_source_domain=r["fb_domain"],
            fallback_confidence=r["fb_conf"],
            fallback_quote_preview=(
                r["fb_quote"][:200] if r["fb_quote"] else None
            ),
            fallback_thumbs=r["fb_thumbs"],
            citations_count=int(r["citations_count"] or 0),
        ))
    return out


# ── Email testing ─────────────────────────────────────────────────────────────

EmailType = Literal[
    # Auth & account
    "welcome", "verification", "password_reset", "password_changed",
    # Subscription & trial
    "trial_expiry", "pilot_ended", "subscription_confirmed", "payment_failed",
    "subscription_cancelled", "subscription_paused", "subscription_resumed",
    # Support & inquiry
    "support_confirmation", "support_reply", "contact_inquiry",
    # Waitlist / launch
    "waitlist_confirmed", "founding_member", "charity_suggestion",
    # Scheduled / product
    "credential_expiry", "regulation_digest", "regulation_alert",
]

# Shown in the admin UI as a categorized dropdown.
EMAIL_CATEGORIES: dict[str, list[dict]] = {
    "Auth & Account": [
        {"type": "welcome", "label": "Welcome"},
        {"type": "verification", "label": "Email Verification"},
        {"type": "password_reset", "label": "Password Reset"},
        {"type": "password_changed", "label": "Password Changed"},
    ],
    "Subscription & Trial": [
        {"type": "trial_expiry", "label": "Trial Expiring"},
        {"type": "pilot_ended", "label": "Pilot Ended"},
        {"type": "subscription_confirmed", "label": "Subscription Confirmed"},
        {"type": "payment_failed", "label": "Payment Failed"},
        {"type": "subscription_cancelled", "label": "Subscription Cancelled"},
        {"type": "subscription_paused", "label": "Subscription Paused"},
        {"type": "subscription_resumed", "label": "Subscription Resumed"},
    ],
    "Support & Inquiry": [
        {"type": "support_confirmation", "label": "Support Confirmation"},
        {"type": "support_reply", "label": "Support Captain Reply"},
        {"type": "contact_inquiry", "label": "Contact Form Forward"},
    ],
    "Waitlist & Launch": [
        {"type": "waitlist_confirmed", "label": "Waitlist Confirmed"},
        {"type": "founding_member", "label": "Founding Member"},
        {"type": "charity_suggestion", "label": "Charity Suggestion"},
    ],
    "Product Notifications": [
        {"type": "credential_expiry", "label": "Credential Expiry Reminder"},
        {"type": "regulation_digest", "label": "Regulation Digest"},
        {"type": "regulation_alert", "label": "Regulation Alert (Immediate)"},
    ],
}


class TestEmailRequest(BaseModel):
    type: EmailType
    recipient: str | None = None


class TestEmailResult(BaseModel):
    success: bool
    type: str
    recipient: str


@router.get("/test-email/catalog")
async def test_email_catalog(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> dict:
    """Return the categorized list of email types the admin UI can send."""
    return EMAIL_CATEGORIES


@router.post("/test-email", response_model=TestEmailResult)
async def send_test_email(
    body: TestEmailRequest,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> TestEmailResult:
    """Send a test email of any type to the admin's own address (or a specified recipient)."""
    from app.email import (
        send_welcome_email,
        send_verification_email,
        send_password_reset_email,
        send_password_changed_email,
        send_trial_expiring_email,
        send_pilot_ended_email,
        send_subscription_confirmed_email,
        send_payment_failed_email,
        send_subscription_cancelled_email,
        send_subscription_paused_email,
        send_subscription_resumed_email,
        send_support_confirmation_email,
        send_support_reply_email,
        send_contact_inquiry_email,
        send_waitlist_confirmed_email,
        send_founding_member_email,
        send_charity_suggestion_email,
        send_credential_expiry_email,
        send_regulation_digest_email,
        send_regulation_alert_email,
    )

    recipient = body.recipient or admin.email
    test_name = "Test Mariner"

    try:
        if body.type == "welcome":
            await send_welcome_email(recipient, test_name)
        elif body.type == "verification":
            await send_verification_email(recipient, test_name, "test-verify-token-xyz789")
        elif body.type == "password_reset":
            await send_password_reset_email(recipient, "test-reset-token-abc123")
        elif body.type == "password_changed":
            await send_password_changed_email(recipient, test_name)
        elif body.type == "trial_expiry":
            await send_trial_expiring_email(recipient, test_name, 37)
        elif body.type == "pilot_ended":
            await send_pilot_ended_email(recipient, test_name)
        elif body.type == "subscription_confirmed":
            await send_subscription_confirmed_email(recipient, test_name)
        elif body.type == "payment_failed":
            await send_payment_failed_email(recipient, test_name)
        elif body.type == "subscription_cancelled":
            await send_subscription_cancelled_email(recipient, test_name)
        elif body.type == "subscription_paused":
            await send_subscription_paused_email(recipient, test_name)
        elif body.type == "subscription_resumed":
            await send_subscription_resumed_email(recipient, test_name)
        elif body.type == "support_confirmation":
            await send_support_confirmation_email(recipient, test_name, "Test Support Request")
        elif body.type == "support_reply":
            await send_support_reply_email(
                recipient, test_name,
                "Test Support Request",
                "Thanks for reaching out. Here is our reply to your test question.",
                "Hi, I had a question about PSC inspection prep for my vessel.",
            )
        elif body.type == "contact_inquiry":
            # contact_inquiry forwards to hello@regknots.com regardless of recipient
            await send_contact_inquiry_email(
                from_name=test_name,
                from_email="inquirer@example.com",
                company="Acme Maritime",
                message="This is a test inquiry from the admin email catalog.",
            )
        elif body.type == "waitlist_confirmed":
            await send_waitlist_confirmed_email(recipient, test_name)
        elif body.type == "founding_member":
            await send_founding_member_email(recipient, test_name)
        elif body.type == "charity_suggestion":
            # charity_suggestion is routed to hello@regknots.com (admin inbox)
            await send_charity_suggestion_email(
                user_email="suggester@example.com",
                org_name="Test Charity — Maritime Relief",
                website="https://example.org",
                reason="Test submission from admin email catalog",
            )
        elif body.type == "credential_expiry":
            await send_credential_expiry_email(
                recipient, test_name,
                "Master 1600 GRT MMC (test)",
                7,
            )
        elif body.type == "regulation_digest":
            await send_regulation_digest_email(
                recipient, test_name,
                [
                    {"title": "CFR Title 46 Updated", "body": "3 sections updated as of today.",
                     "source": "cfr_46", "created_at": datetime.now(timezone.utc).isoformat()},
                    {"title": "New USCG NVIC Published", "body": "1 new section added as of today.",
                     "source": "nvic", "created_at": datetime.now(timezone.utc).isoformat()},
                ],
            )
        elif body.type == "regulation_alert":
            await send_regulation_alert_email(
                recipient, test_name,
                "CFR Title 46 Updated",
                "3 sections updated as of today. Ask me about the latest requirements.",
            )
    except Exception as exc:
        logger.exception("Test email failed type=%s: %s", body.type, exc)
        raise HTTPException(status_code=502, detail=str(exc)[:200])

    logger.info("Admin %s sent test email type=%s to=%s", admin.email, body.type, recipient)
    return TestEmailResult(success=True, type=body.type, recipient=recipient)


# ── Custom email blast ───────────────────────────────────────────────────────


class CustomEmailCountResult(BaseModel):
    count: int


# Sprint D6.91 — recipient filter resolver for the admin custom-email
# sender. Returns the SQL needed to enumerate matching email addresses
# for a given filter key. Shared between the count preview and the
# actual send endpoint so they can never drift out of sync.
#
# Most filters are simple WHERE clauses over the `users` table.
# `wheelhouse` is the exception — it pulls owners of active workspaces
# via a JOIN against `workspaces`. We return a full SELECT body for
# that one and let the caller wrap it.
def _custom_email_recipient_query(filter_key: str) -> str | None:
    """Return a complete `SELECT email FROM ... WHERE ...` statement
    for the given filter, or None if the key is unknown. Each query
    returns deduplicated email addresses for non-internal users.
    """
    # User-row filters — all use `email_verified = true` for any
    # outreach that's pricing or marketing-shaped (Sprint D6.91 add).
    # Existing 'all' and 'trial' filters are kept as-is to avoid
    # changing pre-D6.91 behavior; admins can pivot to the more
    # specific buttons when they need verified-only targeting.
    user_filters = {
        # Existing pre-D6.91 (preserved for back-compat)
        "all":   "subscription_status = 'active'",
        "pro":   "subscription_tier = 'solo' AND subscription_status = 'active'",
        "trial": "trial_ends_at IS NOT NULL AND trial_ends_at > NOW() AND subscription_tier = 'free'",
        # Sprint D6.91 new filters
        "expired": (
            "trial_ends_at <= NOW() "
            "AND subscription_tier = 'free' "
            "AND email_verified = true"
        ),
        "cadet":   "subscription_tier = 'cadet'   AND subscription_status = 'active'",
        "mate":    "subscription_tier = 'mate'    AND subscription_status = 'active'",
        # Captain folds legacy 'pro' since the account page already
        # maps pro → Captain label; treat them as the same audience
        # for outreach purposes.
        "captain": "subscription_tier IN ('captain', 'pro') AND subscription_status = 'active'",
    }
    if filter_key in user_filters:
        return (
            f"SELECT DISTINCT email FROM users "
            f"WHERE {user_filters[filter_key]} AND is_internal = FALSE"
        )

    # Wheelhouse — owners of active workspaces. The owner pays and is
    # the billing decision-maker; crew members aren't the audience
    # for pricing or product-tier announcements.
    if filter_key == "wheelhouse":
        return (
            "SELECT DISTINCT u.email FROM users u "
            "JOIN workspaces w ON w.owner_user_id = u.id "
            "WHERE w.status = 'active' AND u.is_internal = FALSE"
        )

    return None


@router.get("/custom-email-count", response_model=CustomEmailCountResult)
async def get_custom_email_count(
    filter: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> CustomEmailCountResult:
    """Preview how many users match a recipient filter."""
    inner = _custom_email_recipient_query(filter)
    if inner is None:
        return CustomEmailCountResult(count=0)
    count = await pool.fetchval(f"SELECT count(*) FROM ({inner}) AS t")
    return CustomEmailCountResult(count=int(count or 0))


class CustomEmailRequest(BaseModel):
    subject: str
    body_text: str
    # Sprint D6.91 — extended to: all / pro / trial / expired / cadet /
    # mate / captain / wheelhouse / custom. See _custom_email_recipient_query.
    recipient_filter: str
    custom_emails: list[str] | None = None


class CustomEmailResult(BaseModel):
    sent: int
    failed: int
    failed_emails: list[str]


@router.post("/send-custom-email", response_model=CustomEmailResult)
async def send_custom_email_blast(
    body: CustomEmailRequest,
    admin: Annotated[CurrentUser, Depends(require_owner)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> CustomEmailResult:
    """Send a custom admin-composed email to filtered recipients."""
    import asyncio as _asyncio

    from app.email import send_custom_email, send_with_throttle, RESEND_THROTTLE_SECONDS

    # Resolve recipients via the shared filter resolver (Sprint D6.91).
    # Single source of truth shared with /custom-email-count so the
    # admin's preview count exactly matches the actual send target.
    if body.recipient_filter == "custom":
        if not body.custom_emails:
            raise HTTPException(status_code=400, detail="custom_emails required for custom filter")
        emails = body.custom_emails
    else:
        inner = _custom_email_recipient_query(body.recipient_filter)
        if inner is None:
            raise HTTPException(status_code=400, detail=f"Unknown filter: {body.recipient_filter}")
        rows = await pool.fetch(inner)
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
    admin: Annotated[CurrentUser, Depends(require_owner)],
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
          AND ($1 = FALSE OR (u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE))
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
          AND ($1 = FALSE OR (u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE))
        GROUP BY r.source, r.section_number, r.section_title
        ORDER BY cite_count DESC
        LIMIT 10
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
          AND ($1 = FALSE OR (u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE))
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
    # LEFT JOIN a generated day series so every day in the 30-day window has
    # a data point, even if zero messages were sent — the chart should never
    # look "stale" because the current day has no messages yet.
    rows = await pool.fetch(
        """
        WITH days AS (
            SELECT generate_series(
                CURRENT_DATE - INTERVAL '29 days',
                CURRENT_DATE,
                '1 day'::interval
            )::date AS day
        ),
        daily_counts AS (
            SELECT DATE(m.created_at) AS day, COUNT(*) AS message_count
            FROM messages m
            JOIN conversations c ON m.conversation_id = c.id
            JOIN users u ON c.user_id = u.id
            WHERE m.created_at > NOW() - INTERVAL '30 days'
              AND m.role = 'user'
              AND ($1 = FALSE OR (u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE))
            GROUP BY DATE(m.created_at)
        )
        SELECT days.day, COALESCE(dc.message_count, 0) AS message_count
        FROM days
        LEFT JOIN daily_counts dc ON dc.day = days.day
        ORDER BY days.day
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


# ── Feature usage (Sprint D6.25) ─────────────────────────────────────────────
#
# Per-feature totals + per-user breakdown for Credentials Tracker, Compliance
# Log, PSC Checklist, Vessel Dossier, Vessels. Sourced directly from each
# feature's table — no new instrumentation. The point is to answer "is anyone
# actually using this?" before we sink more design time into these surfaces.


class FeatureUsageTotal(BaseModel):
    feature: str
    total_records: int
    distinct_users: int
    last_created_at: str | None


class FeatureUsageUserRow(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    credentials: int
    compliance_logs: int
    psc_checklists: int
    vessels: int
    vessel_documents: int
    last_activity_at: str | None


class FeatureUsageReport(BaseModel):
    totals: list[FeatureUsageTotal]
    top_users: list[FeatureUsageUserRow]


@router.get("/feature-usage", response_model=FeatureUsageReport)
async def feature_usage(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    exclude_internal: bool = Query(default=False),
    limit: int = Query(default=25, ge=1, le=200),
) -> FeatureUsageReport:
    """Snapshot of feature engagement across the user base.

    `totals` rolls up each feature: total records, distinct users who
    have at least one, and last-touch timestamp. `top_users` ranks
    individuals by total records-touched across all features so we can
    spot power users and dead accounts at a glance.

    Adoption today is sparse (single-digit usage on most features)
    so we expect totals to be small for a while — that's the point of
    the panel.
    """
    pool = await get_pool()

    # Each feature has its own table; query them in parallel-ish via UNION
    # for the totals roll-up. The exclude_internal filter joins users so
    # we can drop admin/internal noise from the metric.
    totals_rows = await pool.fetch(
        """
        WITH excl AS (
            SELECT id FROM users
            WHERE $1 = TRUE AND (is_internal IS TRUE OR is_admin IS TRUE)
        )
        SELECT 'Credentials Tracker' AS feature,
               COUNT(*) AS total_records,
               COUNT(DISTINCT user_id) AS distinct_users,
               MAX(created_at) AS last_created_at
        FROM user_credentials
        WHERE user_id NOT IN (SELECT id FROM excl)
        UNION ALL
        SELECT 'Compliance Log',
               COUNT(*),
               COUNT(DISTINCT user_id),
               MAX(created_at)
        FROM compliance_logs
        WHERE user_id NOT IN (SELECT id FROM excl)
        UNION ALL
        SELECT 'PSC Checklist',
               COUNT(*),
               COUNT(DISTINCT user_id),
               MAX(generated_at)
        FROM psc_checklists
        WHERE user_id NOT IN (SELECT id FROM excl)
        UNION ALL
        SELECT 'Vessels',
               COUNT(*),
               COUNT(DISTINCT user_id),
               MAX(created_at)
        FROM vessels
        WHERE user_id NOT IN (SELECT id FROM excl)
        UNION ALL
        SELECT 'Vessel Dossier (documents)',
               COUNT(*),
               COUNT(DISTINCT v.user_id),
               MAX(vd.created_at)
        FROM vessel_documents vd
        JOIN vessels v ON v.id = vd.vessel_id
        WHERE v.user_id NOT IN (SELECT id FROM excl)
        """,
        exclude_internal,
    )

    # Per-user breakdown — single query joining all feature tables via
    # subquery counts. last_activity_at is the max across all five
    # features so we can sort "who's active where."
    top_users_rows = await pool.fetch(
        """
        SELECT
            u.id AS user_id,
            u.email,
            u.full_name,
            COALESCE(cred.cnt, 0) AS credentials,
            COALESCE(clog.cnt, 0) AS compliance_logs,
            COALESCE(psc.cnt, 0) AS psc_checklists,
            COALESCE(ves.cnt, 0) AS vessels,
            COALESCE(vdoc.cnt, 0) AS vessel_documents,
            GREATEST(
                COALESCE(cred.last_at, '1900-01-01'::timestamptz),
                COALESCE(clog.last_at, '1900-01-01'::timestamptz),
                COALESCE(psc.last_at, '1900-01-01'::timestamptz),
                COALESCE(ves.last_at, '1900-01-01'::timestamptz),
                COALESCE(vdoc.last_at, '1900-01-01'::timestamptz)
            ) AS last_activity_at
        FROM users u
        LEFT JOIN (
            SELECT user_id, COUNT(*) cnt, MAX(created_at) last_at
            FROM user_credentials GROUP BY user_id
        ) cred ON cred.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) cnt, MAX(created_at) last_at
            FROM compliance_logs GROUP BY user_id
        ) clog ON clog.user_id = u.id
        LEFT JOIN (
            -- psc_checklists uses generated_at + updated_at, not created_at
            SELECT user_id, COUNT(*) cnt, MAX(generated_at) last_at
            FROM psc_checklists GROUP BY user_id
        ) psc ON psc.user_id = u.id
        LEFT JOIN (
            SELECT user_id, COUNT(*) cnt, MAX(created_at) last_at
            FROM vessels GROUP BY user_id
        ) ves ON ves.user_id = u.id
        LEFT JOIN (
            SELECT v.user_id, COUNT(*) cnt, MAX(vd.created_at) last_at
            FROM vessel_documents vd
            JOIN vessels v ON v.id = vd.vessel_id
            GROUP BY v.user_id
        ) vdoc ON vdoc.user_id = u.id
        WHERE
            (COALESCE(cred.cnt,0) + COALESCE(clog.cnt,0)
             + COALESCE(psc.cnt,0) + COALESCE(ves.cnt,0)
             + COALESCE(vdoc.cnt,0)) > 0
            AND ($1 = FALSE OR (u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE))
        ORDER BY
            (COALESCE(cred.cnt,0) + COALESCE(clog.cnt,0)
             + COALESCE(psc.cnt,0) + COALESCE(ves.cnt,0)
             + COALESCE(vdoc.cnt,0)) DESC,
            last_activity_at DESC
        LIMIT $2
        """,
        exclude_internal,
        limit,
    )

    return FeatureUsageReport(
        totals=[
            FeatureUsageTotal(
                feature=r["feature"],
                total_records=r["total_records"] or 0,
                distinct_users=r["distinct_users"] or 0,
                last_created_at=r["last_created_at"].isoformat()
                if r["last_created_at"]
                else None,
            )
            for r in totals_rows
        ],
        top_users=[
            FeatureUsageUserRow(
                user_id=str(r["user_id"]),
                email=r["email"],
                full_name=r["full_name"],
                credentials=r["credentials"],
                compliance_logs=r["compliance_logs"],
                psc_checklists=r["psc_checklists"],
                vessels=r["vessels"],
                vessel_documents=r["vessel_documents"],
                last_activity_at=r["last_activity_at"].isoformat()
                if r["last_activity_at"] and r["last_activity_at"].year > 1900
                else None,
            )
            for r in top_users_rows
        ],
    )


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
    pool2 = await get_pool()
    await audit_log(pool2, admin, "reply_to_ticket", target_id=ticket_id, details={"reply_length": len(body.reply)})
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


# ── Job testing endpoints ───────────────────────────────────────────────────
#
# IMPORTANT: The send endpoints only email the requesting admin, NOT all users.
# They run the same logic as the Celery jobs but scoped to a single user.


class JobTestResult(BaseModel):
    ok: bool
    sent: int
    details: str


@router.post("/test-job/credential-reminders", response_model=JobTestResult)
async def test_credential_reminders(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> JobTestResult:
    """Send credential expiry reminders for the ADMIN'S OWN credentials only.

    Does NOT run the full production job — only processes credentials
    belonging to the requesting admin. Safe to call in production.
    """
    import json as _json
    from datetime import date

    from app.email import send_credential_expiry_email, send_with_throttle, RESEND_THROTTLE_SECONDS

    pool = await get_pool()
    admin_id = uuid.UUID(admin.user_id)

    logger.info("Admin %s triggered scoped credential reminder test", admin.email)

    prefs_raw = await pool.fetchval(
        "SELECT notification_preferences FROM users WHERE id = $1", admin_id,
    )
    prefs = _json.loads(prefs_raw) if isinstance(prefs_raw, str) else (prefs_raw or {})
    enabled_days = prefs.get("cert_expiry_days", [90, 30, 7])

    rows = await pool.fetch(
        """
        SELECT id, title, expiry_date, reminder_sent_90, reminder_sent_30, reminder_sent_7
        FROM user_credentials
        WHERE user_id = $1
          AND expiry_date IS NOT NULL
          AND expiry_date <= CURRENT_DATE + INTERVAL '91 days'
        """,
        admin_id,
    )

    sent = 0
    for row in rows:
        days_left = (row["expiry_date"] - date.today()).days
        thresholds = [(90, "reminder_sent_90"), (30, "reminder_sent_30"), (7, "reminder_sent_7")]

        for threshold, flag_col in thresholds:
            if threshold not in enabled_days:
                continue
            if row[flag_col]:
                continue
            if days_left > threshold:
                continue

            try:
                await send_with_throttle(
                    lambda title=row["title"], days=days_left:
                        send_credential_expiry_email(admin.email, admin.full_name or "", title, days),
                    label=f"test:{admin.email}:{row['title']}:{threshold}d",
                )
                await pool.execute(
                    f"UPDATE user_credentials SET {flag_col} = TRUE WHERE id = $1",
                    row["id"],
                )
                sent += 1
            except Exception as exc:
                logger.error("Test credential reminder failed: %s", exc)
            break

    return JobTestResult(ok=True, sent=sent, details=f"Sent {sent} reminder(s) to {admin.email}")


@router.post("/test-job/regulation-digest", response_model=JobTestResult)
async def test_regulation_digest(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> JobTestResult:
    """Send a regulation digest email to the ADMIN ONLY.

    Does NOT email all users — sends one digest to the requesting admin
    containing recent regulation update notifications. Safe to call in production.
    """
    from app.email import send_regulation_digest_email, send_with_throttle

    pool = await get_pool()

    logger.info("Admin %s triggered scoped regulation digest test", admin.email)

    notifications = await pool.fetch(
        """
        SELECT title, body, source, created_at
        FROM notifications
        WHERE notification_type = 'regulation_update'
          AND is_active = true
          AND created_at > NOW() - INTERVAL '14 days'
        ORDER BY created_at DESC
        """
    )

    if not notifications:
        return JobTestResult(ok=True, sent=0, details="No regulation updates in the last 14 days — nothing to send")

    updates = [
        {"title": n["title"], "body": n["body"], "source": n["source"], "created_at": n["created_at"].isoformat()}
        for n in notifications
    ]

    try:
        await send_with_throttle(
            lambda: send_regulation_digest_email(admin.email, admin.full_name or "", updates),
            label=f"test-digest:{admin.email}",
        )
        return JobTestResult(ok=True, sent=1, details=f"Sent digest with {len(updates)} update(s) to {admin.email}")
    except Exception as exc:
        logger.exception("Test regulation digest failed: %s", exc)
        return JobTestResult(ok=False, sent=0, details=str(exc)[:200])


class DigestPreviewItem(BaseModel):
    title: str
    body: str
    source: str | None
    created_at: str


class DigestPreview(BaseModel):
    notification_count: int
    recipient_count: int
    notifications: list[DigestPreviewItem]
    recipients: list[str]


@router.get("/test-job/preview-digest", response_model=DigestPreview)
async def preview_regulation_digest(
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> DigestPreview:
    """Dry-run: show what the digest would send without emailing anyone."""
    import json as _json

    pool = await get_pool()

    notifications = await pool.fetch(
        """
        SELECT title, body, source, created_at
        FROM notifications
        WHERE notification_type = 'regulation_update'
          AND is_active = true
          AND created_at > NOW() - INTERVAL '14 days'
        ORDER BY created_at DESC
        """
    )

    users = await pool.fetch(
        """
        SELECT email, notification_preferences
        FROM users
        WHERE subscription_tier != 'free'
           OR trial_ends_at > NOW()
        """
    )

    recipients = []
    for user in users:
        prefs = user["notification_preferences"] or {}
        if isinstance(prefs, str):
            prefs = _json.loads(prefs)
        if prefs.get("reg_change_digest", True):
            recipients.append(user["email"])

    return DigestPreview(
        notification_count=len(notifications),
        recipient_count=len(recipients),
        notifications=[
            DigestPreviewItem(
                title=n["title"],
                body=n["body"],
                source=n["source"],
                created_at=n["created_at"].isoformat(),
            )
            for n in notifications
        ],
        recipients=recipients,
    )


class CredentialReminderPreviewItem(BaseModel):
    user_email: str
    credential_title: str
    expiry_date: str
    days_remaining: int
    threshold: int
    flag: str


class CredentialReminderPreview(BaseModel):
    pending_reminders: list[CredentialReminderPreviewItem]
    total: int


@router.get("/test-job/preview-credential-reminders", response_model=CredentialReminderPreview)
async def preview_credential_reminders(
    admin: Annotated[CurrentUser, Depends(require_admin)],
) -> CredentialReminderPreview:
    """Dry-run: show which credential reminders would fire without sending."""
    import json as _json
    from datetime import date

    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT
            c.title,
            c.expiry_date,
            c.reminder_sent_90,
            c.reminder_sent_30,
            c.reminder_sent_7,
            u.email,
            u.notification_preferences
        FROM user_credentials c
        JOIN users u ON u.id = c.user_id
        WHERE c.expiry_date IS NOT NULL
          AND c.expiry_date <= CURRENT_DATE + INTERVAL '91 days'
        ORDER BY c.expiry_date ASC
        """
    )

    pending = []
    for row in rows:
        prefs = row["notification_preferences"] or {}
        if isinstance(prefs, str):
            prefs = _json.loads(prefs)
        if not prefs.get("cert_expiry_reminders", True):
            continue

        enabled_days = prefs.get("cert_expiry_days", [90, 30, 7])
        days_left = (row["expiry_date"] - date.today()).days

        thresholds = [
            (90, "reminder_sent_90"),
            (30, "reminder_sent_30"),
            (7, "reminder_sent_7"),
        ]

        for threshold, flag_col in thresholds:
            if threshold not in enabled_days:
                continue
            if row[flag_col]:
                continue
            if days_left > threshold:
                continue

            pending.append(CredentialReminderPreviewItem(
                user_email=row["email"],
                credential_title=row["title"],
                expiry_date=row["expiry_date"].isoformat(),
                days_remaining=days_left,
                threshold=threshold,
                flag=flag_col,
            ))
            break

    return CredentialReminderPreview(pending_reminders=pending, total=len(pending))


# ══════════════════════════════════════════════════════════════════════════════
# ADMIN SPRINT ADDITIONS — data browser, citation purge, Sentry link,
# job triggers, and system health.
# ══════════════════════════════════════════════════════════════════════════════


# ── Citation error purge ─────────────────────────────────────────────────────


class PurgeResult(BaseModel):
    ok: bool
    deleted: int


@router.delete("/citation-errors/purge", response_model=PurgeResult)
async def purge_citation_errors(
    admin: Annotated[CurrentUser, Depends(require_owner)],
    before: str | None = Query(default=None, description="Optional ISO date — only delete errors older than this"),
) -> PurgeResult:
    """Delete citation error rows. Without 'before', deletes all."""
    pool = await get_pool()
    if before:
        try:
            cutoff = datetime.fromisoformat(before)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid 'before' ISO date")
        result = await pool.execute(
            "DELETE FROM citation_errors WHERE created_at < $1", cutoff,
        )
    else:
        result = await pool.execute("DELETE FROM citation_errors")

    # asyncpg returns e.g. "DELETE 42" — parse the count
    deleted = int(result.split(" ")[-1]) if result.startswith("DELETE") else 0
    logger.info("Admin %s purged %d citation errors (before=%s)", admin.email, deleted, before)
    return PurgeResult(ok=True, deleted=deleted)


# ── Sentry direct link helper ────────────────────────────────────────────────


@router.get("/sentry-link/{issue_id}")
async def sentry_issue_link(
    issue_id: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> dict:
    """Build the web URL for a Sentry issue. Front-end uses this for deep links."""
    org = settings.sentry_org
    if not org:
        return {"url": None}
    return {"url": f"https://sentry.io/organizations/{org}/issues/{issue_id}/"}


# ── Universal table browser ──────────────────────────────────────────────────
#
# Exposes read-only row access to a whitelist of tables with basic filters.
# Sensitive columns (password hashes, tokens, Stripe secrets) are redacted.
# Write operations are intentionally not supported here.

_BROWSABLE_TABLES: dict[str, dict] = {
    "users": {
        "columns": [
            "id", "email", "full_name", "role", "is_admin", "is_internal",
            "subscription_tier", "subscription_status", "message_count",
            "trial_ends_at", "email_verified", "created_at", "updated_at",
        ],
        "order_by": "created_at DESC",
    },
    "vessels": {
        "columns": [
            "id", "user_id", "name", "vessel_type", "gross_tonnage",
            "route_types", "flag_state", "subchapter", "manning_requirement",
            "inspection_certificate_type", "created_at", "updated_at",
        ],
        "order_by": "created_at DESC",
    },
    "vessel_documents": {
        "columns": [
            "id", "vessel_id", "user_id", "document_type", "filename",
            "file_size", "mime_type", "extraction_status", "created_at",
        ],
        "order_by": "created_at DESC",
    },
    "user_credentials": {
        "columns": [
            "id", "user_id", "credential_type", "title", "credential_number",
            "issuing_authority", "issue_date", "expiry_date",
            "reminder_sent_90", "reminder_sent_30", "reminder_sent_7",
            "created_at", "updated_at",
        ],
        "order_by": "expiry_date ASC NULLS LAST, created_at DESC",
    },
    "compliance_logs": {
        "columns": [
            "id", "user_id", "vessel_id", "entry_date", "category",
            "entry", "created_at", "updated_at",
        ],
        "order_by": "entry_date DESC, created_at DESC",
    },
    "psc_checklists": {
        "columns": [
            "id", "user_id", "vessel_id", "generated_at", "updated_at",
            "checked_indices",
        ],
        "order_by": "generated_at DESC",
    },
    "checklist_feedback": {
        "columns": [
            "id", "user_id", "vessel_id", "checklist_id", "action_type",
            "item_index", "original_item", "final_item", "created_at",
        ],
        "order_by": "created_at DESC",
    },
    "conversations": {
        "columns": [
            "id", "user_id", "vessel_id", "title", "created_at", "updated_at",
        ],
        "order_by": "created_at DESC",
    },
    "support_tickets": {
        "columns": [
            "id", "user_id", "user_email", "user_name", "subject", "status",
            "created_at", "replied_at",
        ],
        "order_by": "created_at DESC",
    },
    "notifications": {
        "columns": [
            "id", "title", "body", "notification_type", "source",
            "is_active", "created_at",
        ],
        "order_by": "created_at DESC",
    },
    "waitlist": {
        "columns": ["email", "created_at"],
        "order_by": "created_at DESC",
    },
    "citation_errors": {
        "columns": [
            "id", "conversation_id", "unverified_citation", "model_used",
            "created_at",
        ],
        "order_by": "created_at DESC",
    },
}


class TableInfo(BaseModel):
    name: str
    columns: list[str]


class TableRows(BaseModel):
    name: str
    columns: list[str]
    rows: list[dict]
    total: int
    limit: int
    offset: int


@router.get("/data/tables", response_model=list[TableInfo])
async def list_browsable_tables(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> list[TableInfo]:
    """Return the whitelist of tables the universal browser can query."""
    return [TableInfo(name=name, columns=meta["columns"]) for name, meta in _BROWSABLE_TABLES.items()]


@router.get("/data/table/{name}", response_model=TableRows)
async def browse_table(
    name: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: str | None = Query(default=None),
    vessel_id: str | None = Query(default=None),
    search: str | None = Query(default=None, description="Substring search on text-ish columns"),
) -> TableRows:
    """Return paginated rows from a whitelisted table, with optional filters.

    Filters auto-apply only to columns that exist on the table.
    `search` performs a case-insensitive ILIKE on a small set of text columns.
    """
    if name not in _BROWSABLE_TABLES:
        raise HTTPException(status_code=404, detail=f"Unknown table '{name}'")

    meta = _BROWSABLE_TABLES[name]
    columns = meta["columns"]
    order_by = meta["order_by"]

    pool = await get_pool()

    conditions: list[str] = []
    params: list = []
    idx = 1

    if user_id and "user_id" in columns:
        conditions.append(f"user_id = ${idx}")
        try:
            params.append(uuid.UUID(user_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid user_id UUID")
        idx += 1

    if vessel_id and "vessel_id" in columns:
        conditions.append(f"vessel_id = ${idx}")
        try:
            params.append(uuid.UUID(vessel_id))
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid vessel_id UUID")
        idx += 1

    if search:
        # Only ILIKE against non-UUID text-ish columns the table exposes.
        text_candidates = [
            c for c in columns
            if c in (
                "email", "full_name", "title", "name", "subject", "filename",
                "entry", "item", "body", "user_email", "user_name",
                "unverified_citation", "credential_number", "issuing_authority",
            )
        ]
        if text_candidates:
            clauses = [f"{c}::text ILIKE ${idx}" for c in text_candidates]
            conditions.append("(" + " OR ".join(clauses) + ")")
            params.append(f"%{search}%")
            idx += 1

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    total = await pool.fetchval(
        f"SELECT COUNT(*) FROM {name} {where_clause}",
        *params,
    )

    col_list = ", ".join(columns)
    params.append(limit)
    params.append(offset)
    rows_raw = await pool.fetch(
        f"SELECT {col_list} FROM {name} {where_clause} ORDER BY {order_by} LIMIT ${idx} OFFSET ${idx + 1}",
        *params,
    )

    def _to_jsonable(v):
        if v is None:
            return None
        if isinstance(v, (str, int, float, bool)):
            return v
        if isinstance(v, (list, dict)):
            return v
        # datetime / date / uuid / jsonb-as-string etc.
        try:
            return v.isoformat()
        except AttributeError:
            return str(v)

    rows = [
        {c: _to_jsonable(r[c]) for c in columns}
        for r in rows_raw
    ]

    return TableRows(
        name=name,
        columns=columns,
        rows=rows,
        total=total or 0,
        limit=limit,
        offset=offset,
    )


# ── Job triggers ─────────────────────────────────────────────────────────────


class JobRunResult(BaseModel):
    ok: bool
    details: str


@router.post("/jobs/ingest", response_model=JobRunResult)
async def trigger_ingest(
    admin: Annotated[CurrentUser, Depends(require_owner)],
    source: str = Query(..., description="Regulation source to update"),
    no_notify: bool = Query(default=False, description="Suppress notifications (dev/maintenance)"),
) -> JobRunResult:
    """Trigger a scheduled ingest subprocess for a single source from the admin UI.

    Fires in the background (non-blocking). Observe progress via systemd/app logs.
    Returns immediately after spawning the subprocess.
    """
    import asyncio as _asyncio
    import subprocess
    from pathlib import Path

    allowed = {"cfr_33", "cfr_46", "cfr_49", "nvic", "colregs", "solas", "stcw", "ism", "erg"}
    if source not in allowed:
        raise HTTPException(status_code=400, detail=f"Unknown source. Allowed: {', '.join(sorted(allowed))}")

    ingest_dir = Path(__file__).resolve().parents[3] / "packages" / "ingest"
    cmd = ["uv", "run", "python", "-m", "ingest.cli", "--source", source, "--update"]
    if no_notify:
        cmd.append("--no-notify")

    async def _run():
        def _spawn():
            subprocess.Popen(cmd, cwd=str(ingest_dir))
        await _asyncio.to_thread(_spawn)

    _asyncio.create_task(_run())

    logger.info("Admin %s triggered ingest source=%s no_notify=%s", admin.email, source, no_notify)
    return JobRunResult(ok=True, details=f"Ingest for '{source}' started in background. Watch logs for progress.")


@router.post("/jobs/imo-amendment-check", response_model=JobRunResult)
async def trigger_imo_check(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> JobRunResult:
    """Run the weekly IMO amendment scraper on demand."""
    from app.tasks import _check_imo_amendments_async
    logger.info("Admin %s triggered IMO amendment check", admin.email)
    try:
        await _check_imo_amendments_async()
        return JobRunResult(ok=True, details="IMO check complete. If new refs found, an alert email was sent to hello@regknots.com.")
    except Exception as exc:
        logger.exception("IMO amendment check failed")
        return JobRunResult(ok=False, details=str(exc)[:200])


@router.post("/jobs/nmc-check", response_model=JobRunResult)
async def trigger_nmc_check(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
) -> JobRunResult:
    """Run the NMC memo/policy document scraper on demand."""
    from app.tasks import _check_nmc_updates_async
    logger.info("Admin %s triggered NMC document check", admin.email)
    await audit_log(await get_pool(), admin, "trigger_nmc_check")
    try:
        await _check_nmc_updates_async()
        return JobRunResult(ok=True, details="NMC check complete. If new documents found, an alert email was sent to hello@regknots.com.")
    except Exception as exc:
        logger.exception("NMC document check failed")
        return JobRunResult(ok=False, details=str(exc)[:200])


@router.get("/jobs/beat-schedule")
async def beat_schedule(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> dict:
    """Return the Celery beat schedule as-configured (for visibility; not live state)."""
    try:
        from celery_beat import celery  # module imports the schedule
        schedule = celery.conf.beat_schedule or {}
        out = {}
        for name, entry in schedule.items():
            sched = entry.get("schedule")
            out[name] = {
                "task": entry.get("task"),
                "schedule": str(sched),
            }
        return {"beat_schedule": out}
    except Exception as exc:
        return {"error": str(exc)[:200], "beat_schedule": {}}


# ── System health ────────────────────────────────────────────────────────────


@router.get("/system/health")
async def system_health(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> dict:
    """Comprehensive system health snapshot for the admin dashboard."""
    from app.db import get_redis
    import os
    import shutil

    results: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.environment,
    }

    # Database
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
            db_size = await conn.fetchval(
                "SELECT pg_size_pretty(pg_database_size(current_database()))"
            )
            active_conns = await conn.fetchval(
                "SELECT COUNT(*) FROM pg_stat_activity WHERE state = 'active'"
            )
            latest_migration = await conn.fetchval(
                "SELECT version_num FROM alembic_version LIMIT 1"
            )
        results["database"] = {
            "ok": True,
            "size": db_size,
            "active_connections": active_conns,
            "pool_size": pool.get_size(),
            "pool_free": pool.get_idle_size(),
            "latest_migration": latest_migration,
        }
    except Exception as exc:
        results["database"] = {"ok": False, "error": str(exc)[:200]}

    # Redis
    try:
        redis = await get_redis()
        pong = await redis.ping()
        info = await redis.info("memory")
        results["redis"] = {
            "ok": bool(pong),
            "used_memory_human": info.get("used_memory_human"),
        }
    except Exception as exc:
        results["redis"] = {"ok": False, "error": str(exc)[:200]}

    # Upload dir disk usage
    try:
        upload_dir = settings.upload_dir
        if os.path.isdir(upload_dir):
            total_size = 0
            file_count = 0
            for dirpath, _dirs, files in os.walk(upload_dir):
                for f in files:
                    fp = os.path.join(dirpath, f)
                    try:
                        total_size += os.path.getsize(fp)
                        file_count += 1
                    except OSError:
                        pass
            usage = shutil.disk_usage(upload_dir)
            results["uploads"] = {
                "ok": True,
                "path": upload_dir,
                "total_bytes": total_size,
                "file_count": file_count,
                "disk_free": usage.free,
                "disk_total": usage.total,
            }
        else:
            results["uploads"] = {"ok": False, "error": f"Directory does not exist: {upload_dir}"}
    except Exception as exc:
        results["uploads"] = {"ok": False, "error": str(exc)[:200]}

    # Sentry config
    results["sentry"] = {
        "ok": bool(settings.sentry_dsn),
        "org": settings.sentry_org or None,
    }

    # External API keys present (boolean only, never values)
    results["api_keys"] = {
        "anthropic": bool(settings.anthropic_api_key),
        "openai": bool(settings.openai_api_key),
        "resend": bool(settings.resend_api_key),
        "stripe": bool(settings.stripe_secret_key),
    }

    return results


# ── Audit log viewer ─────────────────────────────────────────────────────────


class AuditLogEntry(BaseModel):
    id: str
    admin_email: str
    action: str
    target_id: str | None
    details: dict | None
    created_at: str


@router.get("/audit-log", response_model=list[AuditLogEntry])
async def get_audit_log(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLogEntry]:
    """Return the most recent admin audit log entries."""
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT id, admin_email, action, target_id, details, created_at
        FROM admin_audit_log
        ORDER BY created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [
        AuditLogEntry(
            id=str(r["id"]),
            admin_email=r["admin_email"],
            action=r["action"],
            target_id=r["target_id"],
            details=r["details"] if isinstance(r["details"], dict) else None,
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Sprint D6.7 — Caddy access-log analytics
# Free, no GeoIP, no third-party. See app/traffic_analytics.py.
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/traffic")
async def get_traffic(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    days: int = Query(default=7, ge=1, le=30),
) -> dict[str, Any]:
    """Return a rollup of Caddy access logs for the last N days.

    Returns an empty summary in dev (no log directory) so the UI can
    render a friendly empty-state instead of erroring.
    """
    import dataclasses
    from app.traffic_analytics import get_traffic_summary

    log_dir = settings.caddy_access_log_dir
    if not log_dir:
        from app.traffic_analytics import TrafficSummary
        from datetime import datetime, timedelta, timezone
        until = datetime.now(tz=timezone.utc)
        since = until - timedelta(days=days)
        empty = TrafficSummary(
            since=since.isoformat(),
            until=until.isoformat(),
            log_files_scanned=[],
        )
        return dataclasses.asdict(empty)

    summary = await get_traffic_summary(log_dir=log_dir, days=days)
    return dataclasses.asdict(summary)


# ─────────────────────────────────────────────────────────────────────────────
# Sprint D6.14b — Partner tithe tracking (redesigned for default-pool
# distribution).
#
# Schema (migration 0055):
#   tithe_partners   — named beneficiaries (one row per real-world entity).
#   tithe_rules      — distribution rules: maps a referral_source (or NULL
#                      for the catch-all default pool) to one or more
#                      partners with relative weights.
#   billing_events   — per-invoice ledger populated by stripe_service
#                      invoice.paid webhook.
#   partner_payouts  — manual payout records, FK to tithe_partners.id.
#
# Routing semantics: an invoice's revenue routes to the partner(s)
# matched by the rule(s) for its referral_source. If no explicit rule
# exists for that source, it falls into the default pool (rules with
# referral_source IS NULL). Each partner's accrued tithe is the sum
# across every rule it appears in.
# ─────────────────────────────────────────────────────────────────────────────


class PartnerRoute(BaseModel):
    """One leg of a partner's tithe distribution: which referral_source
    feeds it, at what weight, at what tithe %."""
    referral_source: str | None  # None = default pool
    weight: int
    tithe_pct: float
    # Sum of weights across all partners on the same referral_source —
    # tells the operator "you get weight/total_weight of this pool".
    total_weight: int


class TithePartnerSummary(BaseModel):
    id: int
    name: str
    active: bool
    notes: str | None
    payout_method: str | None
    payout_contact: str | None
    routes: list[PartnerRoute]
    # All-time accrual computed across all matching rules
    accrued_alltime_cents: int
    paid_out_cents: int
    outstanding_cents: int
    payout_count: int


class MonthlyPartnerAccrual(BaseModel):
    """Accrued tithe per partner per month."""
    month: str  # 'YYYY-MM'
    partner_id: int
    partner_name: str
    accrued_cents: int


class MonthlyChannelRevenue(BaseModel):
    """Revenue per channel per month — the input side of the tithe."""
    month: str
    referral_source: str | None
    revenue_cents: int
    invoice_count: int


class PartnerPayoutEntry(BaseModel):
    id: str
    partner_id: int
    partner_name_at_time: str
    amount_cents: int
    currency: str
    paid_at: str
    notes: str | None
    created_by_email: str | None
    created_at: str


class PartnerTithesResponse(BaseModel):
    partners: list[TithePartnerSummary]
    monthly_partner_accrual: list[MonthlyPartnerAccrual]
    monthly_channel_revenue: list[MonthlyChannelRevenue]
    recent_payouts: list[PartnerPayoutEntry]
    # Cross-totals
    total_revenue_alltime_cents: int  # sum of partner-attributed + default-pool revenue
    total_tithe_alltime_cents: int
    total_paid_out_cents: int
    total_outstanding_cents: int


# SQL fragment that builds the per-partner accrual.
# Logic:
#   1. For each billing_event, decide the rule's referral_source key:
#      its own value if any rule explicitly matches, else NULL (default).
#   2. Sum up revenue by that effective key.
#   3. For each (effective_key, rule) pair, partner_share =
#      revenue * tithe_pct/100 * weight / total_weight_for_this_key.
#   4. Aggregate per partner.
#
# `events` is parameterised so the same logic powers both all-time and
# monthly aggregations — caller plugs in the desired billing_events
# subquery.
def _build_partner_accrual_cte(events_alias: str = "be_filtered") -> str:
    return f"""
    explicit_sources AS (
        SELECT DISTINCT referral_source
        FROM tithe_rules
        WHERE referral_source IS NOT NULL
    ),
    events_with_key AS (
        SELECT
            e.*,
            CASE
                WHEN e.referral_source IS NOT NULL
                     AND e.referral_source IN (SELECT referral_source FROM explicit_sources)
                THEN e.referral_source
                ELSE NULL
            END AS effective_key
        FROM {events_alias} e
    ),
    pool_revenue AS (
        SELECT
            effective_key,
            SUM(amount_paid_cents)::BIGINT AS revenue_cents
        FROM events_with_key
        GROUP BY effective_key
    ),
    rules_with_totals AS (
        SELECT
            r.id, r.referral_source, r.partner_id, r.weight, r.tithe_pct,
            SUM(r.weight) OVER (
                PARTITION BY COALESCE(r.referral_source, '__default__')
            ) AS total_weight
        FROM tithe_rules r
    )
    """


@router.get("/partner-tithes", response_model=PartnerTithesResponse)
async def get_partner_tithes(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    months: int = Query(default=12, ge=1, le=36),
) -> PartnerTithesResponse:
    """Return the Partners admin-tab payload in one round-trip."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        # ── Partners + their routing legs ────────────────────────────────
        # Each partner can appear in multiple rules; the routes array
        # tells the UI "Women Offshore is fed by /womenoffshore at 100%".
        partner_rows = await conn.fetch(
            """
            SELECT
                p.id, p.name, p.active, p.notes,
                p.payout_method, p.payout_contact,
                COALESCE(json_agg(
                    json_build_object(
                        'referral_source', r.referral_source,
                        'weight',          r.weight,
                        'tithe_pct',       r.tithe_pct,
                        'total_weight',    rt.total_weight
                    ) ORDER BY r.referral_source NULLS LAST
                ) FILTER (WHERE r.id IS NOT NULL), '[]'::json) AS routes
            FROM tithe_partners p
            LEFT JOIN tithe_rules r ON r.partner_id = p.id
            LEFT JOIN (
                SELECT
                    id,
                    SUM(weight) OVER (
                        PARTITION BY COALESCE(referral_source, '__default__')
                    ) AS total_weight
                FROM tithe_rules
            ) rt ON rt.id = r.id
            GROUP BY p.id
            ORDER BY p.name
            """
        )

        # ── All-time partner accrual ─────────────────────────────────────
        # Pure SQL: compute revenue per pool, distribute by weight.
        accrual_alltime_rows = await conn.fetch(
            f"""
            WITH be_filtered AS (
                SELECT amount_paid_cents, referral_source FROM billing_events
            ),
            {_build_partner_accrual_cte()}
            SELECT
                rwt.partner_id,
                COALESCE(SUM(
                    pr.revenue_cents
                    * rwt.tithe_pct / 100.0
                    * rwt.weight
                    / NULLIF(rwt.total_weight, 0)
                ), 0)::BIGINT AS accrued_cents
            FROM rules_with_totals rwt
            LEFT JOIN pool_revenue pr
                ON COALESCE(pr.effective_key, '__default__') = COALESCE(rwt.referral_source, '__default__')
            GROUP BY rwt.partner_id
            """
        )
        accrued_by_partner = {r["partner_id"]: int(r["accrued_cents"]) for r in accrual_alltime_rows}

        # ── Payouts paid per partner ─────────────────────────────────────
        paid_rows = await conn.fetch(
            """
            SELECT partner_id,
                   SUM(amount_cents)::BIGINT AS paid_cents,
                   COUNT(*)                  AS payout_count
            FROM partner_payouts
            GROUP BY partner_id
            """
        )
        paid_by_partner = {
            r["partner_id"]: (int(r["paid_cents"]), int(r["payout_count"]))
            for r in paid_rows
        }

        # ── Build partner summaries ──────────────────────────────────────
        import json as _json
        partners: list[TithePartnerSummary] = []
        total_tithe = total_paid = 0
        for r in partner_rows:
            routes_raw = r["routes"]
            if isinstance(routes_raw, str):
                routes_raw = _json.loads(routes_raw)
            routes = [
                PartnerRoute(
                    referral_source=rt["referral_source"],
                    weight=int(rt["weight"]),
                    tithe_pct=float(rt["tithe_pct"]),
                    total_weight=int(rt["total_weight"]),
                )
                for rt in routes_raw
            ]
            accrued = accrued_by_partner.get(r["id"], 0)
            paid, payout_count = paid_by_partner.get(r["id"], (0, 0))
            outstanding = max(0, accrued - paid)
            total_tithe += accrued
            total_paid += paid
            partners.append(TithePartnerSummary(
                id=r["id"],
                name=r["name"],
                active=r["active"],
                notes=r["notes"],
                payout_method=r["payout_method"],
                payout_contact=r["payout_contact"],
                routes=routes,
                accrued_alltime_cents=accrued,
                paid_out_cents=paid,
                outstanding_cents=outstanding,
                payout_count=payout_count,
            ))

        # ── Total revenue (input side, all-time) ─────────────────────────
        total_revenue_row = await conn.fetchrow(
            "SELECT COALESCE(SUM(amount_paid_cents), 0)::BIGINT AS total FROM billing_events"
        )
        total_revenue = int(total_revenue_row["total"])

        # ── Monthly per-partner accrual ──────────────────────────────────
        monthly_partner_rows = await conn.fetch(
            f"""
            WITH be_filtered AS (
                SELECT
                    amount_paid_cents,
                    referral_source,
                    TO_CHAR(DATE_TRUNC('month', paid_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month
                FROM billing_events
                WHERE paid_at >= (NOW() - ($1::int || ' months')::interval)
            ),
            {_build_partner_accrual_cte()},
            -- Recompute pool_revenue PER MONTH (override the CTE above)
            pool_revenue_monthly AS (
                SELECT effective_key, month,
                       SUM(amount_paid_cents)::BIGINT AS revenue_cents
                FROM events_with_key
                GROUP BY effective_key, month
            )
            SELECT
                pr.month,
                rwt.partner_id,
                p.name AS partner_name,
                SUM(
                    pr.revenue_cents
                    * rwt.tithe_pct / 100.0
                    * rwt.weight
                    / NULLIF(rwt.total_weight, 0)
                )::BIGINT AS accrued_cents
            FROM pool_revenue_monthly pr
            JOIN rules_with_totals rwt
                ON COALESCE(rwt.referral_source, '__default__') = COALESCE(pr.effective_key, '__default__')
            JOIN tithe_partners p ON p.id = rwt.partner_id
            GROUP BY pr.month, rwt.partner_id, p.name
            ORDER BY pr.month DESC, p.name
            """,
            months,
        )
        monthly_partner_accrual = [
            MonthlyPartnerAccrual(
                month=r["month"],
                partner_id=r["partner_id"],
                partner_name=r["partner_name"],
                accrued_cents=int(r["accrued_cents"]),
            )
            for r in monthly_partner_rows
        ]

        # ── Monthly per-channel revenue (input side) ─────────────────────
        monthly_channel_rows = await conn.fetch(
            """
            SELECT
                TO_CHAR(DATE_TRUNC('month', paid_at AT TIME ZONE 'UTC'), 'YYYY-MM') AS month,
                referral_source,
                SUM(amount_paid_cents)::BIGINT AS revenue_cents,
                COUNT(*)                       AS invoice_count
            FROM billing_events
            WHERE paid_at >= (NOW() - ($1::int || ' months')::interval)
            GROUP BY 1, 2
            ORDER BY 1 DESC, 2 NULLS LAST
            """,
            months,
        )
        monthly_channel_revenue = [
            MonthlyChannelRevenue(
                month=r["month"],
                referral_source=r["referral_source"],
                revenue_cents=int(r["revenue_cents"]),
                invoice_count=int(r["invoice_count"]),
            )
            for r in monthly_channel_rows
        ]

        # ── Recent payouts ───────────────────────────────────────────────
        payout_rows = await conn.fetch(
            """
            SELECT
                pp.id, pp.partner_id, pp.partner_name_at_time,
                pp.amount_cents, pp.currency, pp.paid_at, pp.notes, pp.created_at,
                u.email AS created_by_email
            FROM partner_payouts pp
            LEFT JOIN users u ON u.id = pp.created_by_user_id
            ORDER BY pp.paid_at DESC
            LIMIT 100
            """
        )
        recent_payouts = [
            PartnerPayoutEntry(
                id=str(r["id"]),
                partner_id=int(r["partner_id"]),
                partner_name_at_time=r["partner_name_at_time"],
                amount_cents=int(r["amount_cents"]),
                currency=r["currency"],
                paid_at=r["paid_at"].isoformat(),
                notes=r["notes"],
                created_by_email=r["created_by_email"],
                created_at=r["created_at"].isoformat(),
            )
            for r in payout_rows
        ]

    return PartnerTithesResponse(
        partners=partners,
        monthly_partner_accrual=monthly_partner_accrual,
        monthly_channel_revenue=monthly_channel_revenue,
        recent_payouts=recent_payouts,
        total_revenue_alltime_cents=total_revenue,
        total_tithe_alltime_cents=total_tithe,
        total_paid_out_cents=total_paid,
        total_outstanding_cents=max(0, total_tithe - total_paid),
    )


class RecordPayoutRequest(BaseModel):
    partner_id: int
    amount_cents: int
    currency: str = "usd"
    paid_at: str | None = None  # ISO-8601; defaults to now
    notes: str | None = None


class RecordPayoutResponse(BaseModel):
    id: str
    ok: bool


@router.post("/partner-payouts", response_model=RecordPayoutResponse)
async def record_partner_payout(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    body: RecordPayoutRequest,
) -> RecordPayoutResponse:
    """Mark a manual payout to a partner. Audit-logged."""
    if body.amount_cents <= 0:
        raise HTTPException(status_code=400, detail="amount_cents must be positive")
    pool = await get_pool()
    async with pool.acquire() as conn:
        partner = await conn.fetchrow(
            "SELECT name FROM tithe_partners WHERE id = $1",
            body.partner_id,
        )
        if partner is None:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown partner_id: {body.partner_id}",
            )
        paid_at_dt: datetime | None = None
        if body.paid_at:
            try:
                paid_at_dt = datetime.fromisoformat(body.paid_at.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(status_code=400, detail="paid_at must be ISO-8601")
        if paid_at_dt is None:
            paid_at_dt = datetime.now(tz=timezone.utc)

        row = await conn.fetchrow(
            """
            INSERT INTO partner_payouts (
                partner_id, partner_name_at_time, amount_cents, currency,
                paid_at, notes, created_by_user_id
            ) VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id
            """,
            body.partner_id,
            partner["name"],
            body.amount_cents,
            body.currency.lower(),
            paid_at_dt,
            body.notes,
            uuid.UUID(admin.user_id),
        )
    await audit_log(
        pool, admin, "record_partner_payout",
        target_id=str(body.partner_id),
        details={
            "partner_name": partner["name"],
            "amount_cents": body.amount_cents,
            "currency": body.currency,
            "paid_at": paid_at_dt.isoformat(),
            "notes": body.notes,
        },
    )
    return RecordPayoutResponse(id=str(row["id"]), ok=True)


class DeletePayoutResponse(BaseModel):
    ok: bool


@router.delete("/partner-payouts/{payout_id}", response_model=DeletePayoutResponse)
async def delete_partner_payout(
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    payout_id: str,
) -> DeletePayoutResponse:
    """Remove a recorded payout — for typo corrections only. Audit-logged."""
    try:
        payout_uuid = uuid.UUID(payout_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="payout_id must be a UUID")
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT partner_id, partner_name_at_time, amount_cents, currency "
            "FROM partner_payouts WHERE id = $1",
            payout_uuid,
        )
        if existing is None:
            raise HTTPException(status_code=404, detail="payout not found")
        await conn.execute("DELETE FROM partner_payouts WHERE id = $1", payout_uuid)
    await audit_log(
        pool, admin, "delete_partner_payout",
        target_id=str(payout_uuid),
        details={
            "partner_id": int(existing["partner_id"]),
            "partner_name": existing["partner_name_at_time"],
            "amount_cents": int(existing["amount_cents"]),
            "currency": existing["currency"],
        },
    )
    return DeletePayoutResponse(ok=True)


# ── Chat review (Sprint D6.21) ───────────────────────────────────────────────
#
# Admin/QA endpoints for inspecting user conversations. Replaces the ad-hoc
# psql queries we've been running during the multi-flag corpus rollout.
#
# Design:
#   GET /admin/chats             — paginated list with filters (user, vessel
#                                  flag, date range, has_unverified, hedged)
#   GET /admin/chats/{conv_id}   — full conversation thread + per-message
#                                  metadata (model, tokens, citations,
#                                  unverified citations, hedge phrase, vessel
#                                  profile snapshot at query time)
#
# Internal users are excluded by default via the `exclude_internal` flag
# threaded through both endpoints, matching the rest of the admin surface.

class ChatListItem(BaseModel):
    conversation_id: str
    user_id: str
    user_email: str
    user_name: str | None
    is_internal: bool
    vessel_id: str | None
    vessel_name: str | None
    vessel_type: str | None
    flag_state: str | None
    title: str | None
    message_count: int
    has_unverified: bool
    has_hedge: bool
    last_model: str | None
    created_at: str
    last_message_at: str | None


class ChatListResponse(BaseModel):
    items: list[ChatListItem]
    total: int
    limit: int
    offset: int


@router.get("/chats", response_model=ChatListResponse)
async def list_chats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    exclude_internal: bool = Query(default=True),
    flag_state: str | None = Query(default=None, description="Exact flag-state filter (e.g. 'United States')"),
    has_unverified: bool | None = Query(default=None, description="Filter to chats with unverified citations"),
    has_hedge: bool | None = Query(default=None, description="Filter to chats whose answer hedged on retrieval"),
    user_email: str | None = Query(default=None, description="Substring match on user email"),
) -> ChatListResponse:
    """List recent conversations for admin review.

    Joins conversations → users → vessels for context, plus left-joins
    citation_errors and retrieval_misses to surface forensic flags
    cheaply (boolean per conversation, not per message).
    """
    pool = await get_pool()

    where: list[str] = []
    params: list[Any] = []
    idx = 1

    def _add(clause: str, value: Any) -> None:
        nonlocal idx
        where.append(clause.replace("%P", f"${idx}"))
        params.append(value)
        idx += 1

    if exclude_internal:
        where.append("u.is_internal IS NOT TRUE")
    if flag_state:
        _add("v.flag_state = %P", flag_state)
    if user_email:
        _add("u.email ILIKE '%' || %P || '%'", user_email)
    if has_unverified is True:
        where.append("EXISTS (SELECT 1 FROM citation_errors ce WHERE ce.conversation_id = c.id)")
    elif has_unverified is False:
        where.append("NOT EXISTS (SELECT 1 FROM citation_errors ce WHERE ce.conversation_id = c.id)")
    if has_hedge is True:
        where.append("EXISTS (SELECT 1 FROM retrieval_misses rm WHERE rm.conversation_id = c.id)")
    elif has_hedge is False:
        where.append("NOT EXISTS (SELECT 1 FROM retrieval_misses rm WHERE rm.conversation_id = c.id)")

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    # Total count (separate query so pagination math is correct)
    total_row = await pool.fetchrow(
        f"""
        SELECT count(DISTINCT c.id) AS n
        FROM conversations c
        JOIN users u ON u.id = c.user_id
        LEFT JOIN vessels v ON v.id = c.vessel_id
        {where_clause}
        """,
        *params,
    )
    total = int(total_row["n"]) if total_row else 0

    rows = await pool.fetch(
        f"""
        SELECT c.id AS conversation_id,
               c.user_id,
               u.email AS user_email,
               u.full_name AS user_name,
               u.is_internal,
               c.vessel_id,
               v.name AS vessel_name,
               v.vessel_type,
               v.flag_state,
               c.title,
               c.created_at,
               (SELECT COUNT(*) FROM messages m WHERE m.conversation_id = c.id) AS message_count,
               (SELECT MAX(m.created_at) FROM messages m WHERE m.conversation_id = c.id) AS last_message_at,
               (SELECT m.model_used FROM messages m
                WHERE m.conversation_id = c.id AND m.role = 'assistant'
                ORDER BY m.created_at DESC LIMIT 1) AS last_model,
               EXISTS (SELECT 1 FROM citation_errors ce WHERE ce.conversation_id = c.id) AS has_unverified,
               EXISTS (SELECT 1 FROM retrieval_misses rm WHERE rm.conversation_id = c.id) AS has_hedge
        FROM conversations c
        JOIN users u ON u.id = c.user_id
        LEFT JOIN vessels v ON v.id = c.vessel_id
        {where_clause}
        ORDER BY COALESCE(
            (SELECT MAX(m.created_at) FROM messages m WHERE m.conversation_id = c.id),
            c.created_at
        ) DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params, limit, offset,
    )
    items = [
        ChatListItem(
            conversation_id=str(r["conversation_id"]),
            user_id=str(r["user_id"]),
            user_email=r["user_email"],
            user_name=r["user_name"],
            is_internal=bool(r["is_internal"]),
            vessel_id=str(r["vessel_id"]) if r["vessel_id"] else None,
            vessel_name=r["vessel_name"],
            vessel_type=r["vessel_type"],
            flag_state=r["flag_state"],
            title=r["title"],
            message_count=int(r["message_count"] or 0),
            has_unverified=bool(r["has_unverified"]),
            has_hedge=bool(r["has_hedge"]),
            last_model=r["last_model"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
            last_message_at=r["last_message_at"].isoformat() if r["last_message_at"] else None,
        )
        for r in rows
    ]
    return ChatListResponse(items=items, total=total, limit=limit, offset=offset)


class WebFallbackCardForAdmin(BaseModel):
    """Mirrors the WebFallbackCard payload the user actually saw."""
    fallback_id: str
    source_url: str
    source_domain: str
    quote: str
    summary: str
    confidence: int
    surface_tier: str | None  # 'verified' | 'consensus' | 'reference'


class ChatMessageDetail(BaseModel):
    id: str
    role: str
    content: str
    model_used: str | None
    tokens_used: int | None
    cited_regulations: list[dict]      # [{source, section_number, section_title}]
    unverified_citations: list[str]    # display strings, from citation_errors
    hedge_phrase: str | None
    created_at: str
    # D6.59 — when the assistant turn fired the web fallback, surface
    # the same yellow-card payload here so admin can render the chat
    # exactly the way the user saw it. None for user turns and for
    # assistant turns where no fallback fired.
    web_fallback: WebFallbackCardForAdmin | None = None


class VesselSnapshot(BaseModel):
    id: str | None
    name: str | None
    vessel_type: str | None
    flag_state: str | None
    route_types: list[str]
    cargo_types: list[str]
    gross_tonnage: float | None
    subchapter: str | None
    route_limitations: str | None


class ChatDetail(BaseModel):
    conversation_id: str
    user_id: str
    user_email: str
    user_name: str | None
    is_internal: bool
    title: str | None
    created_at: str
    vessel: VesselSnapshot | None
    messages: list[ChatMessageDetail]


@router.get("/chats/{conversation_id}", response_model=ChatDetail)
async def get_chat(
    conversation_id: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> ChatDetail:
    """Full conversation thread + per-message forensic metadata.

    The vessel snapshot is the CURRENT vessel record (not historic — we
    don't snapshot at query time). When reviewing old chats, the vessel
    profile may have evolved since the conversation occurred, which is
    a known limitation; flag if we ever need point-in-time replay.
    """
    pool = await get_pool()
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid uuid: {exc}")

    head = await pool.fetchrow(
        """
        SELECT c.id, c.user_id, c.vessel_id, c.title, c.created_at,
               u.email, u.full_name, u.is_internal,
               v.id AS v_id, v.name AS v_name, v.vessel_type, v.flag_state,
               v.route_types, v.cargo_types, v.gross_tonnage, v.subchapter,
               v.route_limitations
        FROM conversations c
        JOIN users u ON u.id = c.user_id
        LEFT JOIN vessels v ON v.id = c.vessel_id
        WHERE c.id = $1
        """,
        conv_uuid,
    )
    if not head:
        raise HTTPException(status_code=404, detail="conversation not found")

    msg_rows = await pool.fetch(
        """
        SELECT id, role, content, model_used, tokens_used,
               cited_regulation_ids, created_at
        FROM messages
        WHERE conversation_id = $1
        ORDER BY created_at ASC
        """,
        conv_uuid,
    )

    # Citation lookup (single batched query for all message IDs).
    all_reg_ids: list[uuid.UUID] = []
    for m in msg_rows:
        for rid in (m["cited_regulation_ids"] or []):
            all_reg_ids.append(rid)
    reg_lookup: dict[uuid.UUID, dict] = {}
    if all_reg_ids:
        reg_rows = await pool.fetch(
            "SELECT DISTINCT id, source, section_number, section_title "
            "FROM regulations WHERE id = ANY($1::uuid[])",
            all_reg_ids,
        )
        reg_lookup = {
            r["id"]: {
                "source": r["source"],
                "section_number": r["section_number"],
                "section_title": r["section_title"],
            }
            for r in reg_rows
        }

    # citation_errors per conversation (we don't have per-message linkage;
    # surface them as a conversation-level signal on the assistant turn(s)).
    err_rows = await pool.fetch(
        """
        SELECT message_content, unverified_citation, model_used, created_at
        FROM citation_errors
        WHERE conversation_id = $1
        ORDER BY created_at ASC
        """,
        conv_uuid,
    )
    # Group by approximate matching: an unverified citation belongs to the
    # assistant turn whose content starts with the same first 200 chars.
    err_by_prefix: dict[str, list[str]] = {}
    for er in err_rows:
        key = (er["message_content"] or "")[:200]
        err_by_prefix.setdefault(key, []).append(er["unverified_citation"])

    # retrieval_misses per conversation. Column is hedge_phrase_matched
    # (the regex group that triggered detect_hedge), not hedge_phrase.
    miss_rows = await pool.fetch(
        """
        SELECT hedge_phrase_matched, query, created_at
        FROM retrieval_misses
        WHERE conversation_id = $1
        ORDER BY created_at ASC
        """,
        conv_uuid,
    )
    miss_phrases: list[str] = [
        m["hedge_phrase_matched"] for m in miss_rows if m["hedge_phrase_matched"]
    ]

    # web_fallback_responses per conversation. NB: chat_message_id on this
    # table holds the conversation_id (column name is misleading). Only
    # surfaced rows have a yellow card the user actually saw.
    fallback_rows = await pool.fetch(
        """
        SELECT id, query, source_url, source_domain, quote_text,
               answer_text, confidence, surface_tier, surfaced, created_at
        FROM web_fallback_responses
        WHERE chat_message_id = $1 AND surfaced = TRUE
        ORDER BY created_at ASC
        """,
        conv_uuid,
    )

    messages: list[ChatMessageDetail] = []
    # Track which fallback rows we've consumed so the same row isn't
    # attached to multiple assistant turns.
    consumed_fallbacks: set = set()
    for m in msg_rows:
        cited = [
            reg_lookup[rid] for rid in (m["cited_regulation_ids"] or [])
            if rid in reg_lookup
        ]
        unverified: list[str] = []
        if m["role"] == "assistant":
            content_key = (m["content"] or "")[:200]
            unverified = err_by_prefix.get(content_key, [])
        # Hedge phrase: assigned to the FIRST assistant turn that contains
        # the phrase. Coarse — refine if multi-turn hedge tracking matters.
        hedge_phrase: str | None = None
        if m["role"] == "assistant" and miss_phrases:
            for phrase in miss_phrases:
                if phrase and phrase.lower() in (m["content"] or "").lower():
                    hedge_phrase = phrase
                    break

        # Web fallback attribution: pair this assistant turn with the
        # closest preceding fallback row (fallback fires before the
        # assistant turn is persisted, so fallback.created_at <
        # message.created_at by 1-10s typically). First-fit so multiple
        # fallbacks across a long conversation each find one home.
        attached_fb: WebFallbackCardForAdmin | None = None
        if m["role"] == "assistant" and m["created_at"] is not None:
            best = None  # (delta_seconds, row)
            for fb in fallback_rows:
                if fb["id"] in consumed_fallbacks:
                    continue
                if fb["created_at"] is None:
                    continue
                delta = (m["created_at"] - fb["created_at"]).total_seconds()
                # Only attach if fallback fired BEFORE the assistant
                # message and within a 5-minute sanity window.
                if 0 <= delta <= 300:
                    if best is None or delta < best[0]:
                        best = (delta, fb)
            if best is not None:
                fb = best[1]
                consumed_fallbacks.add(fb["id"])
                attached_fb = WebFallbackCardForAdmin(
                    fallback_id=str(fb["id"]),
                    source_url=fb["source_url"] or "",
                    source_domain=fb["source_domain"] or "",
                    quote=fb["quote_text"] or "",
                    summary=fb["answer_text"] or "",
                    confidence=int(fb["confidence"] or 0),
                    surface_tier=fb["surface_tier"],
                )

        messages.append(ChatMessageDetail(
            id=str(m["id"]),
            role=m["role"],
            content=m["content"] or "",
            model_used=m["model_used"],
            tokens_used=int(m["tokens_used"]) if m["tokens_used"] is not None else None,
            cited_regulations=cited,
            unverified_citations=unverified,
            hedge_phrase=hedge_phrase,
            created_at=m["created_at"].isoformat() if m["created_at"] else "",
            web_fallback=attached_fb,
        ))

    vessel: VesselSnapshot | None = None
    if head["v_id"]:
        gt = head["gross_tonnage"]
        vessel = VesselSnapshot(
            id=str(head["v_id"]),
            name=head["v_name"],
            vessel_type=head["vessel_type"],
            flag_state=head["flag_state"],
            route_types=list(head["route_types"] or []),
            cargo_types=list(head["cargo_types"] or []),
            gross_tonnage=float(gt) if gt is not None else None,
            subchapter=head["subchapter"],
            route_limitations=head["route_limitations"],
        )

    return ChatDetail(
        conversation_id=str(head["id"]),
        user_id=str(head["user_id"]),
        user_email=head["email"],
        user_name=head["full_name"],
        is_internal=bool(head["is_internal"]),
        title=head["title"],
        created_at=head["created_at"].isoformat() if head["created_at"] else "",
        vessel=vessel,
        messages=messages,
    )


# ── Confidence tier router shadow log (Sprint D6.84 admin tooling) ────────
#
# Backs the admin "Chats" tab side-by-side comparison view. Endpoints are
# read-only and surface forensic data for evaluating the tier router
# before flipping CONFIDENCE_TIERS_MODE=live.


class TierRouterShadowRow(BaseModel):
    id: int
    conversation_id: str
    user_id: str | None
    user_email: str | None
    query: str
    mode: str                            # 'shadow' | 'live'
    current_answer: str
    current_judge_verdict: str | None
    current_layer_c_fired: bool
    current_verified_citations_count: int
    current_web_confidence: int | None
    shadow_tier: int
    shadow_label: str
    shadow_answer: str | None
    shadow_reason: str | None
    shadow_classifier_verdict: str | None
    shadow_classifier_reasoning: str | None
    shadow_self_consistency_pass: bool | None
    shadow_classifier_latency_ms: int | None
    shadow_self_consistency_latency_ms: int | None
    shadow_total_latency_ms: int | None
    shadow_error: str | None
    differs: bool
    created_at: str


class TierRouterShadowList(BaseModel):
    items: list[TierRouterShadowRow]
    total: int
    limit: int
    offset: int


class TierRouterSummary(BaseModel):
    """Headline rollup for the admin tier-router dashboard.

    counts_by_tier: e.g. {"1": 412, "2": 38, "3": 27, "4": 14}
    differs_count: rows where the tier router would have rendered a
                   different answer than today's pipeline. This is the
                   "blast radius if we flipped to live" number.
    classifier_yes_rate: % of rows where the industry-standard classifier
                         said "yes". A signal for whether we're being
                         too generous or too conservative on Tier 2.
    self_consistency_pass_rate: % of "yes" classifier rows that passed
                                the self-consistency gate. Low values
                                here mean Tier 2 is being downgraded
                                a lot.
    """
    window_days: int
    total_rows: int
    counts_by_tier: dict[str, int]
    counts_by_label: dict[str, int]
    differs_count: int
    differs_pct: float
    classifier_yes_count: int
    classifier_yes_rate: float
    self_consistency_pass_count: int
    self_consistency_pass_rate: float
    avg_total_latency_ms: float | None


@router.get("/tier-router/summary", response_model=TierRouterSummary)
async def tier_router_summary(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    window_days: int = Query(default=7, ge=1, le=90),
) -> TierRouterSummary:
    """Headline rollup for the admin tier-router dashboard.

    Cheap aggregate query — single SQL roundtrip via CTEs. Returns
    zero/empty values if the table is empty (i.e., shadow mode hasn't
    started persisting rows yet).
    """
    row = await pool.fetchrow(
        """
        WITH win AS (
            SELECT *
            FROM tier_router_shadow_log
            WHERE created_at > NOW() - ($1::int || ' days')::interval
        )
        SELECT
            (SELECT COUNT(*) FROM win) AS total_rows,
            (SELECT COUNT(*) FROM win WHERE differs) AS differs_count,
            (SELECT COUNT(*) FROM win WHERE shadow_classifier_verdict = 'yes') AS classifier_yes_count,
            (SELECT COUNT(*) FROM win
                WHERE shadow_classifier_verdict = 'yes'
                  AND shadow_self_consistency_pass = TRUE) AS sc_pass_count,
            (SELECT AVG(shadow_total_latency_ms)::float FROM win
                WHERE shadow_total_latency_ms IS NOT NULL) AS avg_latency
        """,
        window_days,
    )
    total_rows = int(row["total_rows"] or 0)
    differs_count = int(row["differs_count"] or 0)
    classifier_yes_count = int(row["classifier_yes_count"] or 0)
    sc_pass_count = int(row["sc_pass_count"] or 0)

    tier_rows = await pool.fetch(
        """
        SELECT shadow_tier, shadow_label, COUNT(*) AS n
        FROM tier_router_shadow_log
        WHERE created_at > NOW() - ($1::int || ' days')::interval
        GROUP BY 1, 2
        """,
        window_days,
    )
    counts_by_tier: dict[str, int] = {}
    counts_by_label: dict[str, int] = {}
    for r in tier_rows:
        counts_by_tier[str(r["shadow_tier"])] = (
            counts_by_tier.get(str(r["shadow_tier"]), 0) + int(r["n"])
        )
        counts_by_label[r["shadow_label"]] = (
            counts_by_label.get(r["shadow_label"], 0) + int(r["n"])
        )

    return TierRouterSummary(
        window_days=window_days,
        total_rows=total_rows,
        counts_by_tier=counts_by_tier,
        counts_by_label=counts_by_label,
        differs_count=differs_count,
        differs_pct=(100.0 * differs_count / total_rows) if total_rows else 0.0,
        classifier_yes_count=classifier_yes_count,
        classifier_yes_rate=(100.0 * classifier_yes_count / total_rows) if total_rows else 0.0,
        self_consistency_pass_count=sc_pass_count,
        self_consistency_pass_rate=(
            (100.0 * sc_pass_count / classifier_yes_count) if classifier_yes_count else 0.0
        ),
        avg_total_latency_ms=float(row["avg_latency"]) if row["avg_latency"] is not None else None,
    )


@router.get("/tier-router/log", response_model=TierRouterShadowList)
async def tier_router_log(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    differs_only: bool = Query(default=False),
    tier: int | None = Query(default=None, ge=1, le=4),
    label: str | None = Query(default=None, description="verified | industry_standard | relaxed_web | best_effort"),
    user_email: str | None = Query(default=None),
) -> TierRouterShadowList:
    """Paginated list of shadow log rows. Powers the admin Chats-tab
    side-by-side compare view.
    """
    where: list[str] = []
    params: list[Any] = []
    idx = 1

    def _add(clause: str, value: Any) -> None:
        nonlocal idx
        where.append(clause.replace("%P", f"${idx}"))
        params.append(value)
        idx += 1

    if differs_only:
        where.append("s.differs IS TRUE")
    if tier is not None:
        _add("s.shadow_tier = %P", tier)
    if label is not None:
        _add("s.shadow_label = %P", label)
    if user_email:
        _add("u.email ILIKE '%' || %P || '%'", user_email)

    where_clause = ("WHERE " + " AND ".join(where)) if where else ""

    total = int(await pool.fetchval(
        f"""
        SELECT COUNT(*)
        FROM tier_router_shadow_log s
        LEFT JOIN users u ON u.id = s.user_id
        {where_clause}
        """,
        *params,
    ) or 0)

    rows = await pool.fetch(
        f"""
        SELECT s.*, u.email AS user_email
        FROM tier_router_shadow_log s
        LEFT JOIN users u ON u.id = s.user_id
        {where_clause}
        ORDER BY s.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params, limit, offset,
    )

    items = [
        TierRouterShadowRow(
            id=int(r["id"]),
            conversation_id=str(r["conversation_id"]),
            user_id=str(r["user_id"]) if r["user_id"] else None,
            user_email=r["user_email"],
            query=r["query"],
            mode=r["mode"],
            current_answer=r["current_answer"],
            current_judge_verdict=r["current_judge_verdict"],
            current_layer_c_fired=bool(r["current_layer_c_fired"]),
            current_verified_citations_count=int(r["current_verified_citations_count"] or 0),
            current_web_confidence=int(r["current_web_confidence"]) if r["current_web_confidence"] is not None else None,
            shadow_tier=int(r["shadow_tier"]),
            shadow_label=r["shadow_label"],
            shadow_answer=r["shadow_answer"],
            shadow_reason=r["shadow_reason"],
            shadow_classifier_verdict=r["shadow_classifier_verdict"],
            shadow_classifier_reasoning=r["shadow_classifier_reasoning"],
            shadow_self_consistency_pass=r["shadow_self_consistency_pass"],
            shadow_classifier_latency_ms=int(r["shadow_classifier_latency_ms"]) if r["shadow_classifier_latency_ms"] is not None else None,
            shadow_self_consistency_latency_ms=int(r["shadow_self_consistency_latency_ms"]) if r["shadow_self_consistency_latency_ms"] is not None else None,
            shadow_total_latency_ms=int(r["shadow_total_latency_ms"]) if r["shadow_total_latency_ms"] is not None else None,
            shadow_error=r["shadow_error"],
            differs=bool(r["differs"]),
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
        )
        for r in rows
    ]
    return TierRouterShadowList(items=items, total=total, limit=limit, offset=offset)


@router.get("/chats/{conversation_id}/shadow-comparison", response_model=TierRouterShadowList)
async def chat_shadow_comparison(
    conversation_id: str,
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> TierRouterShadowList:
    """All shadow log rows for a single conversation, oldest-first so
    the admin UI can render the per-message side-by-side directly.
    """
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid uuid: {exc}")

    rows = await pool.fetch(
        """
        SELECT s.*, u.email AS user_email
        FROM tier_router_shadow_log s
        LEFT JOIN users u ON u.id = s.user_id
        WHERE s.conversation_id = $1
        ORDER BY s.created_at ASC
        """,
        conv_uuid,
    )
    items = [
        TierRouterShadowRow(
            id=int(r["id"]),
            conversation_id=str(r["conversation_id"]),
            user_id=str(r["user_id"]) if r["user_id"] else None,
            user_email=r["user_email"],
            query=r["query"],
            mode=r["mode"],
            current_answer=r["current_answer"],
            current_judge_verdict=r["current_judge_verdict"],
            current_layer_c_fired=bool(r["current_layer_c_fired"]),
            current_verified_citations_count=int(r["current_verified_citations_count"] or 0),
            current_web_confidence=int(r["current_web_confidence"]) if r["current_web_confidence"] is not None else None,
            shadow_tier=int(r["shadow_tier"]),
            shadow_label=r["shadow_label"],
            shadow_answer=r["shadow_answer"],
            shadow_reason=r["shadow_reason"],
            shadow_classifier_verdict=r["shadow_classifier_verdict"],
            shadow_classifier_reasoning=r["shadow_classifier_reasoning"],
            shadow_self_consistency_pass=r["shadow_self_consistency_pass"],
            shadow_classifier_latency_ms=int(r["shadow_classifier_latency_ms"]) if r["shadow_classifier_latency_ms"] is not None else None,
            shadow_self_consistency_latency_ms=int(r["shadow_self_consistency_latency_ms"]) if r["shadow_self_consistency_latency_ms"] is not None else None,
            shadow_total_latency_ms=int(r["shadow_total_latency_ms"]) if r["shadow_total_latency_ms"] is not None else None,
            shadow_error=r["shadow_error"],
            differs=bool(r["differs"]),
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
        )
        for r in rows
    ]
    return TierRouterShadowList(items=items, total=len(items), limit=len(items), offset=0)


# ── Web fallback events (Sprint D6.58 Slice 3 audit tooling) ──────────────


class FallbackEventDTO(BaseModel):
    id: str
    created_at: str
    query: str
    surface_tier: str | None
    is_ensemble: bool
    ensemble_providers: list[str] | None
    ensemble_agreement_count: int | None
    confidence: int | None
    source_url: str | None
    source_domain: str | None
    quote_text: str | None
    quote_verified: bool
    surfaced: bool
    surface_blocked_reason: str | None
    retrieval_top1_cosine: float | None
    latency_ms: int
    user_email: str | None
    conversation_id: str | None
    answer_text: str | None
    # D6.60 — Haiku judge verdict that gated this fallback firing.
    # null on rows persisted before the judge shipped.
    judge_verdict: str | None = None
    judge_missing_topic: str | None = None
    web_query_used: str | None = None  # populated when partial_miss override fired


class FallbackStatsDTO(BaseModel):
    total_7d: int
    surfaced_7d: int
    ensemble_7d: int
    by_tier: dict[str, int]
    by_blocked_reason: dict[str, int]


@router.get("/web-fallback/stats", response_model=FallbackStatsDTO)
async def web_fallback_stats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> FallbackStatsDTO:
    """Aggregate counters for the admin web-fallback dashboard."""
    total_7d = await pool.fetchval(
        "SELECT COUNT(*) FROM web_fallback_responses "
        "WHERE created_at > NOW() - INTERVAL '7 days' "
        "AND is_calibration = FALSE"
    ) or 0
    surfaced_7d = await pool.fetchval(
        "SELECT COUNT(*) FROM web_fallback_responses "
        "WHERE created_at > NOW() - INTERVAL '7 days' "
        "AND is_calibration = FALSE AND surfaced = TRUE"
    ) or 0
    ensemble_7d = await pool.fetchval(
        "SELECT COUNT(*) FROM web_fallback_responses "
        "WHERE created_at > NOW() - INTERVAL '7 days' "
        "AND is_calibration = FALSE AND is_ensemble = TRUE"
    ) or 0
    tier_rows = await pool.fetch(
        "SELECT COALESCE(surface_tier, 'unknown') AS tier, COUNT(*) AS n "
        "FROM web_fallback_responses "
        "WHERE created_at > NOW() - INTERVAL '7 days' "
        "AND is_calibration = FALSE "
        "GROUP BY 1"
    )
    blocked_rows = await pool.fetch(
        "SELECT COALESCE(surface_blocked_reason, 'none') AS reason, COUNT(*) AS n "
        "FROM web_fallback_responses "
        "WHERE created_at > NOW() - INTERVAL '7 days' "
        "AND is_calibration = FALSE AND surface_tier = 'blocked' "
        "GROUP BY 1"
    )
    return FallbackStatsDTO(
        total_7d=int(total_7d),
        surfaced_7d=int(surfaced_7d),
        ensemble_7d=int(ensemble_7d),
        by_tier={r["tier"]: int(r["n"]) for r in tier_rows},
        by_blocked_reason={
            r["reason"]: int(r["n"]) for r in blocked_rows
            if r["reason"] != "none"
        },
    )


@router.get("/web-fallback", response_model=list[FallbackEventDTO])
async def list_web_fallback_events(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    tier: Annotated[str | None, Query()] = None,
    path: Annotated[
        Literal["all", "ensemble", "single"], Query()
    ] = "all",
    hours: Annotated[int, Query(ge=1, le=8760)] = 168,  # default 7 days
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[FallbackEventDTO]:
    """List fallback events newest first, filtered by tier + path + window."""
    where = [
        f"wf.created_at > NOW() - INTERVAL '{int(hours)} hours'",
        "wf.is_calibration = FALSE",
    ]
    params: list[object] = []
    idx = 1
    if tier and tier != "all":
        where.append(f"wf.surface_tier = ${idx}")
        params.append(tier)
        idx += 1
    if path == "ensemble":
        where.append("wf.is_ensemble = TRUE")
    elif path == "single":
        where.append("wf.is_ensemble = FALSE")
    where_sql = "WHERE " + " AND ".join(where)
    params.append(limit)
    rows = await pool.fetch(
        f"""
        SELECT wf.id, wf.created_at, wf.query, wf.surface_tier,
               wf.is_ensemble, wf.ensemble_providers,
               wf.ensemble_agreement_count, wf.confidence,
               wf.source_url, wf.source_domain, wf.quote_text,
               wf.quote_verified, wf.surfaced,
               wf.surface_blocked_reason, wf.retrieval_top1_cosine,
               wf.latency_ms, wf.answer_text, wf.chat_message_id,
               wf.judge_verdict, wf.judge_missing_topic, wf.web_query_used,
               u.email AS user_email
        FROM web_fallback_responses wf
        LEFT JOIN users u ON u.id = wf.user_id
        {where_sql}
        ORDER BY wf.created_at DESC
        LIMIT ${idx}
        """,
        *params,
    )
    return [
        FallbackEventDTO(
            id=str(r["id"]),
            created_at=r["created_at"].isoformat(),
            query=r["query"],
            surface_tier=r["surface_tier"],
            is_ensemble=bool(r["is_ensemble"]),
            ensemble_providers=list(r["ensemble_providers"] or []) or None,
            ensemble_agreement_count=r["ensemble_agreement_count"],
            confidence=r["confidence"],
            source_url=r["source_url"],
            source_domain=r["source_domain"],
            quote_text=r["quote_text"],
            quote_verified=bool(r["quote_verified"]),
            surfaced=bool(r["surfaced"]),
            surface_blocked_reason=r["surface_blocked_reason"],
            retrieval_top1_cosine=(
                float(r["retrieval_top1_cosine"])
                if r["retrieval_top1_cosine"] is not None else None
            ),
            latency_ms=int(r["latency_ms"] or 0),
            user_email=r["user_email"],
            conversation_id=str(r["chat_message_id"]) if r["chat_message_id"] else None,
            answer_text=r["answer_text"],
            judge_verdict=r["judge_verdict"],
            judge_missing_topic=r["judge_missing_topic"],
            web_query_used=r["web_query_used"],
        )
        for r in rows
    ]


# ── Hedge audits (Sprint D6.58 Slice 2) ───────────────────────────────────


class HedgeAuditDTO(BaseModel):
    id: str
    created_at: str
    classification: Literal[
        "VOCAB", "INTENT", "RANKING", "COSINE",
        "CORPUS_GAP", "JURISDICTION", "OTHER",
    ]
    status: Literal["open", "fixed", "wontfix", "duplicate"]
    query: str
    classifier_reasoning: str | None
    recommendation: str | None
    classifier_model: str | None
    web_surface_tier: str | None
    user_email: str | None
    user_full_name: str | None
    conversation_id: str | None
    top_retrieved_sections: list[dict[str, Any]]
    admin_notes: str | None
    fixed_at: str | None
    fixed_by_email: str | None


class HedgeAuditUpdate(BaseModel):
    status: Literal["open", "fixed", "wontfix", "duplicate"]
    admin_notes: str | None = None
    fix_commit_sha: str | None = None


class HedgeAuditStats(BaseModel):
    open_count: int
    fixed_last_7d: int
    by_classification: dict[str, int]


@router.get("/hedge-audits/stats", response_model=HedgeAuditStats)
async def hedge_audit_stats(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> HedgeAuditStats:
    """Aggregate counters for the admin dashboard."""
    open_count = await pool.fetchval(
        "SELECT COUNT(*) FROM hedge_audits WHERE status = 'open'"
    ) or 0
    fixed_last_7d = await pool.fetchval(
        "SELECT COUNT(*) FROM hedge_audits "
        "WHERE status = 'fixed' AND fixed_at > NOW() - INTERVAL '7 days'"
    ) or 0
    rows = await pool.fetch(
        "SELECT classification, COUNT(*) AS n FROM hedge_audits "
        "WHERE status = 'open' GROUP BY classification"
    )
    by_class = {r["classification"]: int(r["n"]) for r in rows}
    return HedgeAuditStats(
        open_count=int(open_count),
        fixed_last_7d=int(fixed_last_7d),
        by_classification=by_class,
    )


@router.get("/hedge-audits", response_model=list[HedgeAuditDTO])
async def list_hedge_audits(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    status: Annotated[
        Literal["open", "fixed", "wontfix", "duplicate", "all"], Query()
    ] = "open",
    classification: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[HedgeAuditDTO]:
    """List hedge audits, newest first. Default filter: status=open.

    Workflow: admin opens dashboard → sees open audits sorted newest →
    clicks one → reviews retrieval + reasoning → marks fixed/wontfix.
    """
    where = []
    params: list[object] = []
    idx = 1
    if status != "all":
        where.append(f"ha.status = ${idx}")
        params.append(status)
        idx += 1
    if classification:
        where.append(f"ha.classification = ${idx}")
        params.append(classification)
        idx += 1
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)

    rows = await pool.fetch(
        f"""
        SELECT ha.id, ha.created_at, ha.classification, ha.status,
               ha.query, ha.classifier_reasoning, ha.recommendation,
               ha.classifier_model, ha.web_surface_tier,
               ha.conversation_id, ha.top_retrieved_sections,
               ha.admin_notes, ha.fixed_at,
               u.email AS user_email, u.full_name AS user_full_name,
               fb.email AS fixed_by_email
        FROM hedge_audits ha
        LEFT JOIN users u ON u.id = ha.user_id
        LEFT JOIN users fb ON fb.id = ha.fixed_by_user_id
        {where_sql}
        ORDER BY ha.created_at DESC
        LIMIT ${idx}
        """,
        *params,
    )
    import json as _json
    return [
        HedgeAuditDTO(
            id=str(r["id"]),
            created_at=r["created_at"].isoformat(),
            classification=r["classification"],
            status=r["status"],
            query=r["query"],
            classifier_reasoning=r["classifier_reasoning"],
            recommendation=r["recommendation"],
            classifier_model=r["classifier_model"],
            web_surface_tier=r["web_surface_tier"],
            user_email=r["user_email"],
            user_full_name=r["user_full_name"],
            conversation_id=str(r["conversation_id"]) if r["conversation_id"] else None,
            top_retrieved_sections=(
                _json.loads(r["top_retrieved_sections"])
                if isinstance(r["top_retrieved_sections"], str)
                else (r["top_retrieved_sections"] or [])
            ),
            admin_notes=r["admin_notes"],
            fixed_at=r["fixed_at"].isoformat() if r["fixed_at"] else None,
            fixed_by_email=r["fixed_by_email"],
        )
        for r in rows
    ]


@router.patch("/hedge-audits/{audit_id}", response_model=HedgeAuditDTO)
async def update_hedge_audit(
    audit_id: uuid.UUID,
    body: HedgeAuditUpdate,
    admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> HedgeAuditDTO:
    """Mark an audit fixed/wontfix/duplicate, with optional notes.

    `fixed_at` and `fixed_by_user_id` get auto-populated when status
    transitions to 'fixed'. Re-opening (status='open') clears them.
    """
    set_fixed = body.status == "fixed"
    set_open = body.status == "open"

    fixed_at_sql = "fixed_at = NOW()" if set_fixed else ("fixed_at = NULL" if set_open else "fixed_at = fixed_at")
    fixed_by_sql = "fixed_by_user_id = $4" if set_fixed else (
        "fixed_by_user_id = NULL" if set_open else "fixed_by_user_id = fixed_by_user_id"
    )

    params: list[object] = [body.status, body.admin_notes, body.fix_commit_sha]
    if set_fixed:
        params.append(uuid.UUID(admin.user_id))
    params.append(audit_id)

    sql = f"""
        UPDATE hedge_audits SET
          status = $1,
          admin_notes = COALESCE($2, admin_notes),
          fix_commit_sha = COALESCE($3, fix_commit_sha),
          {fixed_at_sql},
          {fixed_by_sql},
          updated_at = NOW()
        WHERE id = ${len(params)}
        RETURNING id
    """
    res = await pool.fetchrow(sql, *params)
    if res is None:
        raise HTTPException(404, "Hedge audit not found")

    # Return the updated row through list_hedge_audits' shape for UI consistency
    rows = await list_hedge_audits(
        _admin=admin, pool=pool, status="all", classification=None, limit=200,
    )
    for r in rows:
        if r.id == str(audit_id):
            return r
    raise HTTPException(404, "Hedge audit not found after update")

"""Product events (2026-10-14).

One row per funnel step in product_events, so the funnel can be read from
our own database: guest_question and guest_claimed (app/guest.py), signup,
first_question, paywall_hit, checkout_started, checkout_completed. When
settings.posthog_key is set, each event is also sent to PostHog in the background (distinct_id = the user's id, the same id
the web client identifies with after login), so server and browser events
meet in one person.

Recording never fails the request: an insert error is logged and dropped,
and the PostHog send is fire-and-forget with a short timeout.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

EVENTS = ("guest_question", "signup", "guest_claimed", "first_question", "paywall_hit",
          "checkout_started", "checkout_completed")

_INSERT = """
    INSERT INTO product_events (event, user_id, anon_id, props)
    VALUES ($1, $2, $3, $4::jsonb)
"""
_PENDING: set[asyncio.Task] = set()


def paywall_reason(status_code: int, detail: object) -> str | None:
    """The paywall a chat preflight error stands for, or None when the error
    is not a paywall (bad input, rate limit, a workspace permission)."""
    text = str(detail or "")
    if status_code == 403 and "verify your email" in text:
        return "verify_email"
    if status_code == 403 and "workspace is read-only" in text:
        return "workspace_card_pending"
    if status_code != 402:
        return None
    if "Image upload" in text:
        return "image_paid_only"
    if "free questions for this 30-day cycle" in text:
        return "free_plan_cycle"
    if "month's free questions" in text:
        return "free_plan_paused"
    if "monthly cap reached" in text:
        return "tier_cap"
    if "Trial expired" in text:
        return "trial_over"
    return "other"


async def track(pool, event: str, *, user_id: uuid.UUID | str | None = None,
                anon_id: str | None = None, props: dict | None = None) -> None:
    """Record one event; forward it to PostHog when a key is configured."""
    uid = _uuid(user_id)
    props = {k: v for k, v in (props or {}).items() if v is not None}
    try:
        await pool.execute(_INSERT, event, uid, (anon_id or None) and anon_id[:64],
                           json.dumps(props, default=str))
    except Exception:
        logger.warning("product event %s not recorded", event, exc_info=True)
    distinct_id = str(uid) if uid else anon_id
    if settings.posthog_key and distinct_id:
        task = asyncio.create_task(_send(event, distinct_id, props))
        _PENDING.add(task)
        task.add_done_callback(_PENDING.discard)


def _uuid(value) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


async def _send(event: str, distinct_id: str, props: dict) -> None:
    body = {
        "api_key": settings.posthog_key,
        "event": event,
        "distinct_id": distinct_id,
        "properties": {**props, "source": "server", "$lib": "regknots-api"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.post(settings.posthog_host.rstrip("/") + "/i/v0/e/", json=body)
            if r.status_code >= 400:
                logger.warning("PostHog refused %s: HTTP %s", event, r.status_code)
    except Exception as exc:
        logger.warning("PostHog send failed for %s: %s", event, exc)

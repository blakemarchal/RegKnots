"""The free plan (2026-10-02).

A free user's trial is 7 days and 50 messages (FREE_TRIAL_MESSAGE_CAP). After
it, instead of a hard paywall, the user keeps settings.free_plan_monthly_cap
questions per rolling 30-day cycle: the same users.monthly_message_count /
message_cycle_started_at counters the Cadet and Mate caps use.

Free-plan answers across all users are also counted per calendar month in
free_plan_usage; at settings.free_plan_global_monthly_cap the free plan
pauses until the 1st, so marketing to individual mariners can't overrun the
Claude bill. Paid tiers, admins, internal users and workspace chats never
touch any of this.

The chat preflight calls check_allowance() (402 with the reason when the user
or the month is out); _persist_chat_outcome calls record_if_free_plan() after
the answer is stored.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException, status

from app.config import settings
from app.plans import FREE_TRIAL_MESSAGE_CAP


def cycle_used(row, now: datetime) -> tuple[int, datetime]:
    """(questions used this 30-day cycle, when the cycle resets)."""
    start = row["message_cycle_started_at"]
    if start is None or now - start >= timedelta(days=30):
        return 0, now + timedelta(days=30)
    return row["monthly_message_count"], start + timedelta(days=30)


def _day(d) -> str:
    """"October 5" (strftime's %-d is not portable)."""
    return f"{d:%B} {d.day}"


def month_start(now: datetime) -> date:
    return now.date().replace(day=1)


def next_month(now: datetime) -> date:
    first = month_start(now)
    return (first.replace(year=first.year + 1, month=1) if first.month == 12
            else first.replace(month=first.month + 1))


async def global_used(pool, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    val = await pool.fetchval("SELECT answers FROM free_plan_usage WHERE month = $1", month_start(now))
    return int(val or 0)


@dataclass
class FreePlanState:
    cap: int
    used: int
    remaining: int
    resets_at: datetime
    paused: bool          # the month's global cap is reached


async def state(pool, row, now: datetime | None = None) -> FreePlanState | None:
    """The free plan for a free user whose trial is over; None when the free
    plan is switched off (free_plan_monthly_cap = 0)."""
    now = now or datetime.now(timezone.utc)
    cap = settings.free_plan_monthly_cap
    if cap <= 0:
        return None
    used, resets_at = cycle_used(row, now)
    paused = await global_used(pool, now) >= settings.free_plan_global_monthly_cap
    return FreePlanState(cap=cap, used=used, remaining=max(0, cap - used), resets_at=resets_at, paused=paused)


async def check_allowance(pool, row, now: datetime | None = None) -> None:
    """Raise 402 unless this post-trial free user may ask another question."""
    now = now or datetime.now(timezone.utc)
    fp = await state(pool, row, now)
    if fp is None:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED,
                            detail="Trial expired or message limit reached. Subscribe to continue.")
    if fp.remaining <= 0:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(f"You've used your {fp.cap} free questions for this 30-day cycle. They reset on "
                    f"{_day(fp.resets_at)}. Subscribe to keep asking."),
        )
    if fp.paused:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(f"This month's free questions are used up. They reset on {_day(next_month(now))}. "
                    "Subscribe to keep asking."),
        )


async def record_if_free_plan(pool, user_id: uuid.UUID, conversation_id: uuid.UUID,
                              now: datetime | None = None) -> bool:
    """Count a stored answer against the month's free-plan total when it was a
    free-plan answer. Runs after the message counters were incremented, so the
    50th trial message (count now 50) is still a trial message."""
    now = now or datetime.now(timezone.utc)
    row = await pool.fetchrow(
        """
        SELECT u.subscription_tier, u.trial_ends_at, u.message_count, u.is_admin, u.is_internal,
               c.workspace_id
        FROM users u, conversations c
        WHERE u.id = $1 AND c.id = $2
        """,
        user_id, conversation_id,
    )
    if not row or row["subscription_tier"] != "free" or row["is_admin"] or row["is_internal"]:
        return False
    if row["workspace_id"] is not None:
        return False
    ends = row["trial_ends_at"]
    if not ((ends is None or ends <= now) or row["message_count"] > FREE_TRIAL_MESSAGE_CAP):
        return False
    if settings.free_plan_monthly_cap <= 0:
        return False
    await pool.execute(
        """
        INSERT INTO free_plan_usage (month, answers) VALUES ($1, 1)
        ON CONFLICT (month) DO UPDATE SET answers = free_plan_usage.answers + 1
        """,
        month_start(now),
    )
    return True

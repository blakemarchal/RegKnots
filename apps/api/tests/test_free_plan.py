"""2026-10-02 — the free plan after the trial, under a global monthly cap."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from app import free_plan
from app.config import settings

NOW = datetime(2026, 10, 2, 15, 0, tzinfo=timezone.utc)
UID = uuid.uuid4()


class Pool:
    """free_plan_usage and one users/conversations row, in memory."""

    def __init__(self, global_used=0, user=None):
        self.usage = {free_plan.month_start(NOW): global_used}
        self.user = user or {}
        self.updates = []

    async def fetchval(self, sql, month):
        return self.usage.get(month)

    async def fetchrow(self, sql, *args):
        return self.user

    async def execute(self, sql, *args):
        if sql.strip().startswith("UPDATE users"):
            self.updates.append(args)
            return
        self.usage[args[0]] = self.usage.get(args[0], 0) + 1


def row(used=3, cycle_age_days=5, trial_days_left=-10, count=60):
    return {"monthly_message_count": used, "message_cycle_started_at": NOW - timedelta(days=cycle_age_days),
            "trial_ends_at": NOW + timedelta(days=trial_days_left), "message_count": count}


def test_state_counts_the_cycle_and_the_month(monkeypatch):
    monkeypatch.setattr(settings, "free_plan_monthly_cap", 10)
    monkeypatch.setattr(settings, "free_plan_global_monthly_cap", 500)
    s = asyncio.run(free_plan.state(Pool(), row(used=3), NOW))
    assert (s.cap, s.used, s.remaining, s.paused) == (10, 3, 7, False)
    assert s.resets_at == NOW - timedelta(days=5) + timedelta(days=30)
    s = asyncio.run(free_plan.state(Pool(), row(used=30, cycle_age_days=31), NOW))   # an old cycle resets
    assert (s.used, s.remaining) == (0, 10)
    assert asyncio.run(free_plan.state(Pool(global_used=500), row(), NOW)).paused
    monkeypatch.setattr(settings, "free_plan_monthly_cap", 0)
    assert asyncio.run(free_plan.state(Pool(), row(), NOW)) is None


def test_allowance_raises_with_the_reason(monkeypatch):
    monkeypatch.setattr(settings, "free_plan_monthly_cap", 10)
    monkeypatch.setattr(settings, "free_plan_global_monthly_cap", 500)
    asyncio.run(free_plan.check_allowance(Pool(), row(used=9), UID, NOW))   # the 10th question is allowed
    with pytest.raises(HTTPException) as exc:
        asyncio.run(free_plan.check_allowance(Pool(), row(used=10), UID, NOW))
    assert exc.value.status_code == 402 and "10 free questions" in exc.value.detail
    assert "October 27" in exc.value.detail                                   # cycle start + 30 days
    with pytest.raises(HTTPException) as exc:
        asyncio.run(free_plan.check_allowance(Pool(global_used=500), row(used=1), UID, NOW))
    assert "November 1" in exc.value.detail
    monkeypatch.setattr(settings, "free_plan_monthly_cap", 0)
    with pytest.raises(HTTPException) as exc:                                # free plan off: old paywall
        asyncio.run(free_plan.check_allowance(Pool(), row(used=0), UID, NOW))
    assert "Trial expired" in exc.value.detail


def test_trial_messages_do_not_use_up_the_free_plan(monkeypatch):
    monkeypatch.setattr(settings, "free_plan_monthly_cap", 10)
    monkeypatch.setattr(settings, "free_plan_global_monthly_cap", 500)
    # the trial ended yesterday; its 30 messages fell in a cycle that began 5 days ago
    during = row(used=30, cycle_age_days=5, trial_days_left=-1)
    s = asyncio.run(free_plan.state(Pool(), during, NOW))
    assert (s.used, s.remaining, s.resets_at) == (0, 10, NOW + timedelta(days=30))
    pool = Pool()
    asyncio.run(free_plan.check_allowance(pool, during, UID, NOW))           # allowed, and the cycle starts now
    assert pool.updates == [(UID, NOW)]


def test_running_out_of_trial_messages_ends_the_trial_then():
    early = row(used=50, cycle_age_days=3, trial_days_left=4, count=50)
    pool = Pool()
    started = asyncio.run(free_plan.start_cycle(pool, UID, early, NOW))
    assert pool.updates == [(UID, NOW)]
    assert (started["trial_ends_at"], started["message_cycle_started_at"], started["monthly_message_count"]) == (NOW, NOW, 0)
    # the next question sees a cycle that began after the trial: nothing to reset
    pool = Pool()
    later = NOW + timedelta(minutes=5)
    assert asyncio.run(free_plan.start_cycle(pool, UID, started | {"monthly_message_count": 1}, later))["monthly_message_count"] == 1
    assert pool.updates == []
    assert free_plan.cycle_used(started | {"monthly_message_count": 1}, later) == (1, NOW + timedelta(days=30))


@pytest.mark.parametrize("user,counted", [
    ({"subscription_tier": "free", "trial_ends_at": NOW - timedelta(days=1), "message_count": 70,
      "is_admin": False, "is_internal": False, "workspace_id": None}, True),
    # still in the trial: the 50th message leaves the count at 50
    ({"subscription_tier": "free", "trial_ends_at": NOW + timedelta(days=3), "message_count": 50,
      "is_admin": False, "is_internal": False, "workspace_id": None}, False),
    # trial days left, but all 50 messages used
    ({"subscription_tier": "free", "trial_ends_at": NOW + timedelta(days=3), "message_count": 51,
      "is_admin": False, "is_internal": False, "workspace_id": None}, True),
    ({"subscription_tier": "mate", "trial_ends_at": None, "message_count": 70,
      "is_admin": False, "is_internal": False, "workspace_id": None}, False),
    ({"subscription_tier": "free", "trial_ends_at": NOW - timedelta(days=1), "message_count": 70,
      "is_admin": False, "is_internal": False, "workspace_id": uuid.uuid4()}, False),     # the fleet pays
    ({"subscription_tier": "free", "trial_ends_at": NOW - timedelta(days=1), "message_count": 70,
      "is_admin": True, "is_internal": False, "workspace_id": None}, False),
])
def test_only_free_plan_answers_count_toward_the_month(monkeypatch, user, counted):
    monkeypatch.setattr(settings, "free_plan_monthly_cap", 10)
    pool = Pool(user=user)
    assert asyncio.run(free_plan.record_if_free_plan(pool, uuid.uuid4(), uuid.uuid4(), NOW)) is counted
    assert pool.usage[free_plan.month_start(NOW)] == (1 if counted else 0)


class BillingPool:
    def __init__(self, user, global_used=0):
        self.user = user
        self.global_used = global_used

    async def fetchrow(self, sql, *args):
        return self.user

    async def fetchval(self, sql, *args):
        return self.global_used


def billing_row(**over):
    base = {"subscription_tier": "free", "subscription_status": "inactive",
            "trial_ends_at": datetime.now(timezone.utc) + timedelta(days=3), "message_count": 50,
            "monthly_message_count": 2, "message_cycle_started_at": datetime.now(timezone.utc) - timedelta(days=5),
            "cancel_at_period_end": False, "current_period_end": None, "billing_interval": None,
            "stripe_subscription_id": None, "referral_source": None, "is_admin": False, "is_internal": False}
    return base | over


@pytest.mark.parametrize("global_used,remaining,paused", [(0, 10, False), (500, 0, True)])
def test_billing_status_reports_the_free_plan_once_the_trial_messages_are_used(
        monkeypatch, global_used, remaining, paused):
    from types import SimpleNamespace
    from app.routers import billing

    monkeypatch.setattr(settings, "free_plan_monthly_cap", 10)
    monkeypatch.setattr(settings, "free_plan_global_monthly_cap", 500)
    pool = BillingPool(billing_row(), global_used)

    async def get_pool():
        return pool

    monkeypatch.setattr(billing, "get_pool", get_pool)
    out = asyncio.run(billing.billing_status(user=SimpleNamespace(user_id=str(uuid.uuid4()))))
    # trial days are left, but all 50 messages are used: the free plan has taken over,
    # and its first cycle starts with the next question (the trial's 2 don't count)
    assert out.free_plan and not out.trial_active and out.free_plan_paused is paused
    assert (out.monthly_message_cap, out.monthly_messages_used, out.monthly_messages_remaining) == (10, 0, remaining)
    assert out.needs_subscription is (remaining == 0) and out.messages_remaining == remaining


def test_billing_status_keeps_the_trial_while_messages_last(monkeypatch):
    from types import SimpleNamespace
    from app.routers import billing

    pool = BillingPool(billing_row(message_count=12))

    async def get_pool():
        return pool

    monkeypatch.setattr(billing, "get_pool", get_pool)
    out = asyncio.run(billing.billing_status(user=SimpleNamespace(user_id=str(uuid.uuid4()))))
    assert out.trial_active and not out.free_plan and out.messages_remaining == 38

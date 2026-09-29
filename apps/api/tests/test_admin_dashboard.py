"""2026-09-29 — /admin/dashboard shapes rows into the dashboard payload, and the
pilot-era bulk reset stays retired."""
import asyncio
import importlib
import uuid
from datetime import date, datetime, timezone

import pytest
from fastapi import HTTPException

DASH = importlib.import_module("app.routers.admin_dashboard")
ADMIN = importlib.import_module("app.routers.admin")

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)


class _Conn:
    """Answers each dashboard query by recognising a fragment of its SQL."""

    def __init__(self, exclude_internal=True):
        self.sql = []

    async def fetch(self, sql, *args):
        self.sql.append(sql)
        if "generate_series" in sql:
            return [{"week_start": date(2026, 9, 21), "signups": 0, "active_users": 1, "questions": 2, "new_paying": 0},
                    {"week_start": date(2026, 9, 28), "signups": 1, "active_users": 0, "questions": 0, "new_paying": 0}]
        if "rm.judge_verdict" in sql:
            return [{"verdict": "partial_miss", "n": 1}, {"verdict": None, "n": 1}]
        if "h.classification" in sql:
            return [{"cause": "CORPUS_GAP", "n": 3}, {"cause": None, "n": 1}]
        if "ORDER BY u.created_at DESC" in sql:
            return [{"id": uuid.uuid4(), "email": "a@example.com", "full_name": None, "role": "mate",
                     "created_at": NOW, "signup_source": "src:ob-0001", "questions": 0}]
        if "regexp_replace" in sql:
            return [{"conversation_id": uuid.uuid4(), "email": "b@example.com", "full_name": "B",
                     "created_at": NOW, "preview": "Does a new deckhand need an orientation?"}]
        if "be.amount_paid_cents, be.subscription_tier" in sql:
            return [{"email": "c@example.com", "amount_paid_cents": 3900, "subscription_tier": "captain",
                     "billing_interval": "month", "paid_at": NOW}]
        raise AssertionError(f"unexpected fetch: {sql[:80]}")

    async def fetchrow(self, sql, *args):
        self.sql.append(sql)
        if "AS returned" in sql:
            return {"signed_up": 64, "asked": 40, "returned": 15, "active_30d": 1, "paying": 2}
        if "AS alltime" in sql:
            return {"d30": 4899, "alltime": 8895, "invoices": 6, "last_paid": NOW}
        if "AS new_7d" in sql:
            return {"new_7d": 2, "open": 205}
        raise AssertionError(f"unexpected fetchrow: {sql[:80]}")

    async def fetchval(self, sql, *args):
        self.sql.append(sql)
        if "LATERAL" in sql:
            return 4899
        if "m.role = 'assistant'" in sql:
            return 2
        if "trial_ends_at BETWEEN" in sql:
            return 0
        raise AssertionError(f"unexpected fetchval: {sql[:80]}")


class _Pool:
    def __init__(self, conn):
        self.conn = conn

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


@pytest.fixture
def conn(monkeypatch):
    c = _Conn()

    async def get_pool():
        return _Pool(c)

    monkeypatch.setattr(DASH, "get_pool", get_pool)
    return c


def test_dashboard_shapes_trends_funnel_money_and_quality(conn):
    d = asyncio.run(DASH.dashboard(_admin=None, exclude_internal=True, weeks=26))
    assert [w.questions for w in d.weeks] == [2, 0]
    assert d.funnel.asked == 40 and d.funnel.returned == 15 and d.funnel.paying == 2
    assert d.revenue.mrr_cents == 4899 and d.revenue.paid_alltime_cents == 8895
    # Every flagged answer counts as hedged; an unjudged one is labelled, not dropped.
    assert d.quality.hedged_7d == 2
    assert d.quality.judge_7d == {"partial_miss": 1, "unjudged": 1}
    assert d.quality.open_audit_causes == {"CORPUS_GAP": 3, "unclassified": 1}
    assert d.recent_questions[0].preview.startswith("Does a new deckhand")
    assert d.recent_payments[0].amount_cents == 3900


def test_dashboard_filters_internal_accounts_only_when_asked(conn):
    asyncio.run(DASH.dashboard(_admin=None, exclude_internal=True, weeks=26))
    assert all("is_admin IS NOT TRUE" in s for s in conn.sql)
    conn.sql.clear()
    asyncio.run(DASH.dashboard(_admin=None, exclude_internal=False, weeks=26))
    assert not any("is_admin IS NOT TRUE" in s for s in conn.sql)


def test_bulk_pilot_reset_is_retired():
    with pytest.raises(HTTPException) as err:
        asyncio.run(ADMIN.reset_all_pilots(admin=None))
    assert err.value.status_code == 410

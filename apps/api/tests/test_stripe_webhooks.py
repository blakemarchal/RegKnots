"""2026-09-26 — Stripe first-purchase interval and the stale-subscription reconciliation.

The webhook endpoint is subscribed to checkout.session.completed, invoice.paid
and customer.subscription.updated/paused/resumed, but not .created or .deleted:
a first purchase never recorded billing_interval, and a subscription that ended
never downgraded its user (kdmarchal+test kept 'pro' months past 2026-05-08).
"""
import asyncio
import importlib
from types import SimpleNamespace

import pytest

S = importlib.import_module("app.stripe_service")

PERIOD_END = 1_790_000_000


def _sub(sub_id="sub_1", interval="month", status="active"):
    item = SimpleNamespace(price=SimpleNamespace(id="price_x", recurring=SimpleNamespace(interval=interval)),
                           current_period_end=PERIOD_END)
    return SimpleNamespace(id=sub_id, customer="cus_1", status=status, items=SimpleNamespace(data=[item]),
                           cancel_at_period_end=False, cancel_at=None, current_period_end=PERIOD_END)


class _Pool:
    def __init__(self, fetchrow_results=(), execute_results=(), fetch_rows=()):
        self.calls = []
        self._fetchrow = list(fetchrow_results)
        self._execute = list(execute_results)
        self._fetch = list(fetch_rows)

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return self._fetchrow.pop(0) if self._fetchrow else None

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return self._execute.pop(0) if self._execute else "UPDATE 1"

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self._fetch


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    monkeypatch.setattr(S, "_configure", lambda: None)

    async def _no_email(*a, **k):
        return None
    import app.email as email
    monkeypatch.setattr(email, "send_subscription_confirmed_email", _no_email)


def test_price_and_interval_reads_objects_and_dicts():
    assert S._price_and_interval(_sub()) == ("price_x", "month")
    as_dict = {"items": {"data": [{"price": {"id": "price_y", "recurring": {"interval": "year"}}}]}}
    assert S._price_and_interval(as_dict) == ("price_y", "year")
    assert S._price_and_interval(SimpleNamespace(items=SimpleNamespace(data=[]))) == (None, None)
    assert S._price_and_interval(object()) == (None, None)       # malformed: logged, not raised


def test_checkout_records_interval_and_period(monkeypatch):
    monkeypatch.setattr(S.stripe.Subscription, "retrieve", staticmethod(lambda sub_id: _sub(sub_id)))
    pool = _Pool(fetchrow_results=[None, {"email": "c@x", "full_name": "C"}])
    asyncio.run(S._on_checkout_completed(SimpleNamespace(customer="cus_1", subscription="sub_1"), pool))
    kind, sql, args = pool.calls[1]
    assert kind == "fetchrow" and "billing_interval = COALESCE($4, billing_interval)" in sql
    assert "current_period_end = COALESCE($5, current_period_end)" in sql
    assert args[1:4] == ("sub_1", "cus_1", "month") and args[4].timestamp() == PERIOD_END


def test_invoice_paid_records_interval_through_the_customer_fallback(monkeypatch):
    monkeypatch.setattr(S.stripe.Subscription, "retrieve", staticmethod(lambda sub_id: _sub(sub_id)))
    invoice = SimpleNamespace(id="in_1", customer="cus_1", subscription="sub_1", amount_paid=3900,
                              amount_due=3900, total=3900, currency="usd", period_start=None,
                              period_end=None, status_transitions=None, created=PERIOD_END - 100)
    row = {"id": "u1", "referral_source": None, "subscription_tier": "captain", "billing_interval": None}
    # the Captain's 2026-09-09 order: invoice.paid before checkout wrote the subscription id
    pool = _Pool(fetchrow_results=[row], execute_results=["UPDATE 0", "UPDATE 1", "INSERT 0 1"])
    asyncio.run(S._on_invoice_paid(invoice, pool))
    updates = [c for c in pool.calls if c[0] == "execute" and "UPDATE users" in c[1]]
    assert len(updates) == 2 and all("billing_interval = COALESCE($3, billing_interval)" in u[1] for u in updates)
    assert all(u[2][2] == "month" for u in updates)
    ledger = [c for c in pool.calls if c[0] == "execute" and "INSERT INTO billing_events" in c[1]]
    assert ledger and ledger[0][2][-1] == "month"         # from the subscription, not the NULL user row


def test_reconcile_downgrades_ended_and_vanished_subscriptions(monkeypatch):
    class Missing(Exception):
        code = "resource_missing"

    def retrieve(sub_id):
        if sub_id == "sub_gone":
            raise Missing("No such subscription")
        return _sub(sub_id, status="canceled")

    synced = []

    async def fake_change(sub, pool):
        synced.append((sub.id, sub.status))

    monkeypatch.setattr(S.stripe.Subscription, "retrieve", staticmethod(retrieve))
    monkeypatch.setattr(S, "_on_subscription_change", fake_change)
    pool = _Pool(fetch_rows=[{"id": "u1", "stripe_subscription_id": "sub_ended"},
                             {"id": "u2", "stripe_subscription_id": "sub_gone"}])
    counts = asyncio.run(S.reconcile_stale_subscriptions(pool))
    assert counts == {"checked": 2, "synced": 1, "missing": 1, "errors": 0}
    assert synced == [("sub_ended", "canceled")]
    fetch_sql = pool.calls[0][1]
    assert "stripe_subscription_id IS NOT NULL" in fetch_sql and "subscription_tier <> 'free'" in fetch_sql
    free = [c for c in pool.calls if c[0] == "execute"]
    assert free and "subscription_tier = 'free'" in free[0][1] and free[0][2] == ("u2",)


def test_reconcile_is_scheduled_daily():
    import celery_beat
    entry = celery_beat.celery.conf.beat_schedule["reconcile-subscriptions-daily"]
    assert entry["task"] == "app.tasks.reconcile_subscriptions"

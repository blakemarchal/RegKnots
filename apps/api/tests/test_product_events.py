"""2026-10-14 — product events: the funnel rows and the PostHog send."""
import asyncio
import json
import uuid

from app import events
from app.config import settings


class Pool:
    def __init__(self, fail=False):
        self.rows = []
        self.fail = fail

    async def execute(self, sql, *args):
        if self.fail:
            raise RuntimeError("db down")
        self.rows.append(args)


def test_paywall_reasons():
    r = events.paywall_reason
    assert r(403, "Please verify your email to continue using RegKnot.") == "verify_email"
    assert r(403, "This workspace is read-only (status: card_pending).") == "workspace_card_pending"
    assert r(403, "You are not a member of that workspace.") is None
    assert r(429, "Too many messages") is None
    assert r(400, "At most 5 images per query.") is None
    assert r(402, "Image upload requires a paid subscription.") == "image_paid_only"
    assert r(402, "You've used your 10 free questions for this 30-day cycle. They reset on Oct 20.") == "free_plan_cycle"
    assert r(402, "This month's free questions are used up.") == "free_plan_paused"
    assert r(402, "Cadet plan monthly cap reached (25 messages). Upgrade to Mate for more.") == "tier_cap"
    assert r(402, "Trial expired or message limit reached. Subscribe to continue.") == "trial_over"
    assert r(402, "something new") == "other"


def test_track_records_and_sends_only_with_a_key(monkeypatch):
    sent = []

    async def fake_send(event, distinct_id, props):
        sent.append((event, distinct_id, props))

    monkeypatch.setattr(events, "_send", fake_send)
    uid = uuid.uuid4()

    async def run(pool, **kw):
        await events.track(pool, "paywall_hit", **kw)
        await asyncio.sleep(0)   # let the background send run

    monkeypatch.setattr(settings, "posthog_key", "")
    pool = Pool()
    asyncio.run(run(pool, user_id=str(uid), props={"reason": "tier_cap", "plan": None}))
    event, user_id, anon_id, props = pool.rows[0]
    assert (event, user_id, anon_id) == ("paywall_hit", uid, None)
    assert json.loads(props) == {"reason": "tier_cap"}   # None values dropped
    assert sent == []

    monkeypatch.setattr(settings, "posthog_key", "phc_test")
    asyncio.run(run(Pool(), user_id=uid, props={"reason": "tier_cap"}))
    asyncio.run(run(Pool(), anon_id="dev-123"))
    asyncio.run(run(Pool()))   # no id at all: recorded, not sent
    assert [(e, d) for e, d, _ in sent] == [("paywall_hit", str(uid)), ("paywall_hit", "dev-123")]


def test_track_never_raises(monkeypatch):
    monkeypatch.setattr(settings, "posthog_key", "")
    asyncio.run(events.track(Pool(fail=True), "signup", user_id="not-a-uuid"))

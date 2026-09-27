"""2026-09-26 — first-touch signup attribution.

None of the 64 external users had a recorded source. users.referral_source
can't carry it: that column drives the charity tithe split and promo pricing.
"""
import asyncio
import importlib
import json
import uuid

import pytest
from fastapi import Response

from app import attribution as A
from app.auth.schemas import RegisterRequest, SignupAttribution

AUTH = importlib.import_module("app.routers.auth")


def test_clean_keeps_known_fields_capped_and_printable():
    raw = SignupAttribution(utm_source=" Newsletter\n", utm_campaign="x" * 300, src="", ref=None,
                            landing_path="/landing")
    out = A.clean(raw)
    assert out == {"utm_source": "Newsletter", "utm_campaign": "x" * 120, "landing_path": "/landing"}
    assert A.clean(None) == {}


@pytest.mark.parametrize("fields,label", [
    ({"src": "OB-3f9a", "utm_source": "email"}, "src:ob-3f9a"),
    ({"utm_source": "Newsletter", "utm_campaign": "oct"}, "utm:newsletter/-/oct"),
    ({"ref": "womenoffshore", "referrer_host": "facebook.com"}, "ref:womenoffshore"),
    ({"referrer_host": "www.Google.com"}, "referrer:google.com"),
    ({"landing_path": "/landing", "first_seen_at": "2026-09-26T20:00:00Z"}, "direct"),
    ({}, None),
])
def test_source_label_precedence(fields, label):
    assert A.source_label(fields) == label


class _Pool:
    def __init__(self):
        self.calls = []

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return None                      # no existing user, no invite, not internal

    async def fetchrow(self, sql, *args):
        self.calls.append(("fetchrow", sql, args))
        return {"id": uuid.uuid4(), "email": args[0], "full_name": args[2], "role": args[3],
                "subscription_tier": "free", "is_admin": False, "email_verified": False}

    async def execute(self, sql, *args):
        self.calls.append(("execute", sql, args))
        return "UPDATE 1"


@pytest.fixture
def pool(monkeypatch):
    p = _Pool()

    async def get_pool():
        return p

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(AUTH, "get_pool", get_pool)
    monkeypatch.setattr(AUTH, "auto_claim_invites_for_user", nothing)
    monkeypatch.setattr(AUTH, "send_welcome_email", nothing)
    monkeypatch.setattr(AUTH, "send_verification_email", nothing)
    return p


def _register(pool, attribution):
    body = RegisterRequest(email="new@example.com", password="pw-123456", full_name="New Mariner",
                           role="other", attribution=attribution)
    asyncio.run(AUTH.register(body, Response()))
    return [c for c in pool.calls if c[0] == "execute" and "signup_source" in c[1]]


def test_register_stores_the_first_touch(pool):
    writes = _register(pool, SignupAttribution(src="ob-3f9a", utm_source="email", landing_path="/landing"))
    assert len(writes) == 1
    _, sql, args = writes[0]
    assert "referral_source" not in sql                       # never the promo-pricing column
    assert args[0] == "src:ob-3f9a"
    assert json.loads(args[1]) == {"utm_source": "email", "src": "ob-3f9a", "landing_path": "/landing"}


def test_register_without_attribution_writes_nothing(pool):
    assert _register(pool, None) == []

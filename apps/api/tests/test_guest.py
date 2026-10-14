"""2026-10-14 — one free answer before signup: the switch, the limits and the
claim (app/guest.py, app/routers/guest_chat.py)."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app import guest
from app.config import settings
from app.routers import guest_chat


class LimitsPool:
    def __init__(self, device=0, ip=0, today=0, month=0):
        self.row = {"device": device, "ip": ip, "today": today, "month": month}

    async def fetchrow(self, sql, *args):
        return self.row


def limits(monkeypatch, **counts):
    monkeypatch.setattr(settings, "anon_ip_daily_cap", 6)
    monkeypatch.setattr(settings, "anon_daily_cap", 30)
    monkeypatch.setattr(settings, "anon_monthly_cap", 300)
    return asyncio.run(guest.check_limits(LimitsPool(**counts), "d", "i"))


def test_off_unless_flag_and_turnstile_secret(monkeypatch):
    monkeypatch.setattr(settings, "anon_chat_enabled", True)
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    assert not guest.enabled()
    monkeypatch.setattr(settings, "turnstile_secret_key", "0x4AAA")
    assert guest.enabled()
    monkeypatch.setattr(settings, "anon_chat_enabled", False)
    assert not guest.enabled()


def test_stream_refuses_while_off(monkeypatch):
    monkeypatch.setattr(settings, "anon_chat_enabled", False)
    body = guest_chat.GuestAskBody(query="Do I need a TSMS?", device_id="device-12345")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(guest_chat.guest_stream(body, request=None, pool=None))
    assert exc.value.status_code == 503 and exc.value.detail["code"] == "guest_off"


def test_limits(monkeypatch):
    limits(monkeypatch)                                    # a first question passes
    for counts, code in [({"device": 1}, "guest_used"), ({"ip": 6}, "guest_ip"),
                         ({"today": 30}, "guest_paused"), ({"month": 300}, "guest_paused")]:
        with pytest.raises(HTTPException) as exc:
            limits(monkeypatch, **counts)
        assert exc.value.status_code == 429 and exc.value.detail["code"] == code
        assert "free account" in exc.value.detail["message"]
    limits(monkeypatch, ip=5, today=29, month=299)         # just under every cap


def test_hashes_and_ip():
    assert guest.keyed_hash("device:abc") == guest.keyed_hash("device:abc") != guest.keyed_hash("device:abd")
    assert len(guest.claim_hash("t")) == 64
    req = SimpleNamespace(headers={"x-forwarded-for": "203.0.113.9, 10.0.0.1"}, client=SimpleNamespace(host="127.0.0.1"))
    assert guest.client_ip(req) == "203.0.113.9"
    req = SimpleNamespace(headers={}, client=SimpleNamespace(host="127.0.0.1"))
    assert guest.client_ip(req) == "127.0.0.1"


class ClaimConn:
    def __init__(self, row):
        self.row, self.executed = row, []

    def transaction(self):
        conn = self

        class _Tx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Tx()

    async def fetchrow(self, sql, *args):
        assert "claimed_by IS NULL" in sql and args[0] == guest.claim_hash("secret")
        return self.row

    async def execute(self, sql, *args):
        self.executed.append((sql.split()[0] + " " + sql.split()[1], args))


class ClaimPool:
    def __init__(self, row, guest_id):
        self.conn, self.guest_id = ClaimConn(row), guest_id

    async def fetchval(self, sql, *args):
        return self.guest_id

    def acquire(self):
        conn = self.conn

        class _Ctx:
            async def __aenter__(self):
                return conn

            async def __aexit__(self, *a):
                return False
        return _Ctx()


def test_claim_moves_the_conversation_and_vessel():
    gid, uid, conv, vessel = (uuid.uuid4() for _ in range(4))
    pool = ClaimPool({"id": uuid.uuid4(), "conversation_id": conv, "vessel_id": vessel}, gid)
    assert asyncio.run(guest.claim(pool, uid, "secret")) == conv
    moved = [args for what, args in pool.conn.executed]
    assert moved[0] == (uid, conv, gid) and moved[1] == (uid, vessel, gid)
    assert [what for what, _ in pool.conn.executed] == [
        "UPDATE conversations", "UPDATE vessels", "UPDATE users", "UPDATE guest_questions"]


def test_claim_ignores_unknown_or_missing_tokens():
    pool = ClaimPool(None, uuid.uuid4())
    assert asyncio.run(guest.claim(pool, uuid.uuid4(), "secret")) is None
    assert asyncio.run(guest.claim(pool, uuid.uuid4(), None)) is None
    assert pool.conn.executed == []

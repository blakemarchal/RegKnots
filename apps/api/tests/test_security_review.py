"""2026-10-16 security review (docs/sprint-audits/security-review-2026-10-16.md):
rate limits, the startup guard, password rules and session revocation, and the
upload checks."""
import asyncio
import io
import uuid

import pytest
from fastapi import HTTPException, Response, UploadFile

from app import ratelimit, uploads
from app.auth.schemas import CurrentUser, RegisterRequest
from app.config import DEV_JWT_SECRET, Settings, production_problems
from app.routers import auth as AUTH


# ── rate limits ──────────────────────────────────────────────────────────────

class FakeRedis:
    def __init__(self):
        self.store = {}

    def pipeline(self):
        redis = self

        class Pipe:
            def __init__(self):
                self.ops = []

            def set(self, key, value, ex=None, nx=False):
                self.ops.append(("set", key, value, nx))

            def incr(self, key):
                self.ops.append(("incr", key))

            async def execute(self):
                out = []
                for op in self.ops:
                    if op[0] == "set":
                        if not (op[3] and op[1] in redis.store):
                            redis.store[op[1]] = op[2]
                        out.append(True)
                    else:
                        redis.store[op[1]] = redis.store.get(op[1], 0) + 1
                        out.append(redis.store[op[1]])
                return out
        return Pipe()


def test_limits_count_in_redis(monkeypatch):
    fake = FakeRedis()

    async def get_redis():
        return fake

    monkeypatch.setattr("app.db.get_redis", get_redis)
    rules = [("t:redis", 3, 60)]
    for _ in range(3):
        asyncio.run(ratelimit.enforce(rules, "slow down"))
    with pytest.raises(HTTPException) as exc:
        asyncio.run(ratelimit.enforce(rules, "slow down"))
    assert exc.value.status_code == 429 and exc.value.detail == "slow down"


def test_limits_stay_on_when_redis_is_down(monkeypatch):
    async def broken():
        raise ConnectionError("redis down")

    monkeypatch.setattr("app.db.get_redis", broken)
    ratelimit._LOCAL.clear()
    rules = [(f"t:local:{uuid.uuid4()}", 2, 60)]
    asyncio.run(ratelimit.enforce(rules, "x"))
    asyncio.run(ratelimit.enforce(rules, "x"))
    with pytest.raises(HTTPException):
        asyncio.run(ratelimit.enforce(rules, "x"))


def test_subjects_are_hashed():
    assert ratelimit.subject("Mate@Example.com ") == ratelimit.subject("mate@example.com")
    assert "example" not in ratelimit.subject("mate@example.com")


# ── startup guard ────────────────────────────────────────────────────────────

def test_production_refuses_the_development_secret():
    assert production_problems(Settings(environment="production", jwt_secret_key=DEV_JWT_SECRET))
    assert production_problems(Settings(environment="production", jwt_secret_key="short"))
    assert production_problems(Settings(environment="production", jwt_secret_key="x" * 64)) == []
    assert production_problems(Settings(environment="development", jwt_secret_key=DEV_JWT_SECRET)) == []


def test_environment_defaults_to_production():
    assert Settings.model_fields["environment"].default == "production"


# ── passwords and sessions ───────────────────────────────────────────────────

def test_register_requires_eight_characters():
    body = RegisterRequest(email="a@example.com", password="short", full_name="A", role="other")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(AUTH.register(body, None, Response()))
    assert exc.value.status_code == 422


class _Conn:
    def __init__(self, log):
        self.log = log

    async def execute(self, sql, *args):
        self.log.append(" ".join(sql.split()))

    def transaction(self):
        class _Tx:
            async def __aenter__(self_inner):
                return self_inner

            async def __aexit__(self_inner, *exc):
                return False
        return _Tx()


class _Pool:
    def __init__(self, row):
        self.row, self.log = row, []

    async def fetchrow(self, sql, *args):
        return self.row

    async def execute(self, sql, *args):
        self.log.append(" ".join(sql.split()))

    def acquire(self):
        conn = _Conn(self.log)

        class _Ctx:
            async def __aenter__(self_inner):
                return conn

            async def __aexit__(self_inner, *exc):
                return False
        return _Ctx()


def _quiet(monkeypatch, pool):
    async def nothing(*a, **k):
        return None

    async def get_pool():
        return pool

    monkeypatch.setattr(AUTH, "get_pool", get_pool)
    monkeypatch.setattr(AUTH, "send_password_changed_email", nothing)
    monkeypatch.setattr(AUTH.ratelimit, "change_password", nothing)
    monkeypatch.setattr(AUTH.ratelimit, "reset_password", nothing)


def test_password_change_ends_other_sessions(monkeypatch):
    pool = _Pool({"hashed_password": AUTH.hash_password("old-password")})
    _quiet(monkeypatch, pool)
    user = CurrentUser(user_id=str(uuid.uuid4()), email="m@example.com", role="captain", tier="captain")
    response = Response()
    asyncio.run(AUTH.change_password(AUTH.PasswordChange(current_password="old-password",
                                                         new_password="new-password-1"), user, response))
    assert any(q.startswith("DELETE FROM refresh_tokens WHERE user_id") for q in pool.log)
    assert any(q.startswith("INSERT INTO refresh_tokens") for q in pool.log)
    assert "refresh_token=" in response.headers.get("set-cookie", "")    # this device stays signed in


def test_password_reset_ends_every_session(monkeypatch):
    from datetime import datetime, timedelta, timezone
    pool = _Pool({"id": uuid.uuid4(), "user_id": uuid.uuid4(), "used": False,
                  "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
                  "email": "m@example.com", "full_name": "M"})
    _quiet(monkeypatch, pool)
    asyncio.run(AUTH.reset_password(AUTH.ResetPasswordRequest(token="t", new_password="new-password-1"), None))
    assert any(q.startswith("DELETE FROM refresh_tokens WHERE user_id") for q in pool.log)


# ── uploads ──────────────────────────────────────────────────────────────────

def test_types_come_from_the_bytes():
    assert uploads.sniff_image_or_pdf(b"\xff\xd8\xff\xe0rest") == "image/jpeg"
    assert uploads.sniff_image_or_pdf(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert uploads.sniff_image_or_pdf(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert uploads.sniff_image_or_pdf(b"%PDF-1.7") == "application/pdf"
    assert uploads.sniff_image_or_pdf(b"<html>not an image") is None
    with pytest.raises(HTTPException):
        uploads.require_image_or_pdf(b"MZ\x90\x00 an executable")
    assert uploads.sniff_audio(b"\x1a\x45\xdf\xa3....") == ("audio/webm", ".webm")
    assert uploads.sniff_audio(b"OggS....") == ("audio/ogg", ".ogg")
    assert uploads.sniff_audio(b"\x00\x00\x00\x20ftypM4A ") == ("audio/mp4", ".m4a")
    assert uploads.sniff_audio(b"ID3\x04....") == ("audio/mpeg", ".mp3")
    assert uploads.sniff_audio(b"%PDF-1.7") is None


def test_reads_stop_past_the_cap():
    small = UploadFile(file=io.BytesIO(b"x" * 10), filename="a")
    assert asyncio.run(uploads.read_capped(small, 10, "too big")) == b"x" * 10
    big = UploadFile(file=io.BytesIO(b"x" * (3 * 1024 * 1024)), filename="b")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(uploads.read_capped(big, 2 * 1024 * 1024, "too big"))
    assert exc.value.detail == "too big"

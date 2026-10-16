"""Request rate limits (2026-10-16 security review, item 2).

Fixed-window counters in Redis: the first hit in a window creates the key
with its expiry (SET NX EX) and every hit increments it, in one pipeline, so
a key can never be left without an expiry.

When Redis can't be reached the limits stay on through an in-process
counter (this API runs one worker), instead of failing open (no limit, the
chat preflight's choice) or closed (nobody can sign in).

Keys hash their subject (an email, an IP), so Redis never holds them in the
clear.
"""
from __future__ import annotations

import hashlib
import logging
import time

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

_LOCAL: dict[str, tuple[int, float]] = {}
_LOCAL_MAX_KEYS = 50_000

MINUTE, HOUR, DAY = 60, 3600, 86400


def subject(value: str | None) -> str:
    """A short stable hash for an email or IP in a key."""
    return hashlib.sha256((value or "").strip().lower().encode()).hexdigest()[:24]


def client_ip(request: Request) -> str:
    """The visitor's IP: Caddy puts it first in X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip()
    return ip or (request.client.host if request.client else "")


def _local_hit(key: str, window: int) -> int:
    now = time.monotonic()
    count, ends = _LOCAL.get(key, (0, 0.0))
    if now >= ends:
        count, ends = 0, now + window
    count += 1
    _LOCAL[key] = (count, ends)
    if len(_LOCAL) > _LOCAL_MAX_KEYS:
        for k in [k for k, (_, e) in _LOCAL.items() if e <= now]:
            _LOCAL.pop(k, None)
    return count


async def hit(key: str, window: int) -> int:
    """Count one request against `key`; returns the count in this window."""
    try:
        from app.db import get_redis
        redis = await get_redis()
        pipe = redis.pipeline()
        pipe.set(f"rl:{key}", 0, ex=window, nx=True)
        pipe.incr(f"rl:{key}")
        _, count = await pipe.execute()
        return int(count)
    except Exception as exc:  # noqa: BLE001 — Redis down: keep limiting in-process
        logger.warning("rate limit: Redis unavailable (%s); using the in-process counter", type(exc).__name__)
        return _local_hit(key, window)


async def enforce(rules: list[tuple[str, int, int]], message: str) -> None:
    """Raise 429 with `message` when any (key, limit, window) rule is over."""
    for key, limit, window in rules:
        if await hit(key, window) > limit:
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=message)


# ── The limits ───────────────────────────────────────────────────────────────

_WAIT = "Too many attempts. Please wait a few minutes and try again."


async def login(request: Request, email: str) -> None:
    await enforce([
        (f"login:email:{subject(email)}", 10, 15 * MINUTE),
        (f"login:ip:{subject(client_ip(request))}", 30, 15 * MINUTE),   # a vessel's crew shares one IP
    ], _WAIT)


async def register(request: Request) -> None:
    await enforce([(f"register:ip:{subject(client_ip(request))}", 10, HOUR)], _WAIT)


async def forgot_password(request: Request, email: str) -> None:
    await enforce([
        (f"forgot:email:{subject(email)}", 3, HOUR),
        (f"forgot:ip:{subject(client_ip(request))}", 10, HOUR),
    ], _WAIT)


async def reset_password(request: Request) -> None:
    await enforce([(f"reset:ip:{subject(client_ip(request))}", 10, HOUR)], _WAIT)


async def change_password(user_id: str) -> None:
    await enforce([(f"password:user:{user_id}", 10, HOUR)], _WAIT)


async def document_scan(user_id: str) -> None:
    """Vision extraction of an uploaded document or credential (a model call each)."""
    await enforce([(f"scan:user:{user_id}", 30, DAY)],
                  "You've reached today's limit for document scans. Please try again tomorrow.")


async def transcription(user_id: str) -> None:
    await enforce([(f"transcribe:user:{user_id}", 100, DAY)],
                  "You've reached today's limit for voice input. Please try again tomorrow.")

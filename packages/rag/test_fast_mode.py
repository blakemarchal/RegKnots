"""2026-10-17 — Opus fast mode (rag.engine._answer_stream): the speed flag on the
answer call, and the fall back to standard speed when the API refuses it."""
import asyncio

import httpx
from anthropic import OverloadedError, RateLimitError

from rag import engine


def _refusal(cls, status):
    req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return cls("refused", response=httpx.Response(status, request=req), body=None)


class _Client:
    """messages.stream(**kw) that refuses fast mode `refuse` times; records retries setting."""

    def __init__(self, refuse=None):
        self.refuse = refuse
        self.calls: list[dict] = []
        self.max_retries = 2
        outer = self

        class _Stream:
            def __init__(self, kw):
                self.kw = kw

            async def __aenter__(self):
                if outer.refuse is not None and "speed" in (self.kw.get("extra_body") or {}):
                    raise outer.refuse
                return self

            async def __aexit__(self, *exc):
                return False

        class _Messages:
            def __init__(self, retries):
                self.retries = retries

            def stream(self, **kw):
                outer.calls.append({**kw, "_retries": self.retries})
                return _Stream(kw)

        self.messages = _Messages(2)

    def with_options(self, max_retries):
        copy = _Client(self.refuse)
        copy.calls = self.calls
        copy.messages = type(self.messages)(max_retries)
        return copy


ARGS = {"model": "claude-opus-5-5", "messages": [], "max_tokens": 10, "extra_body": {"speed": "fast"}}


async def _open(client, args):
    async with engine._answer_stream(client, args) as stream:
        return stream.kw


def test_fast_request_goes_out_without_sdk_retries():
    client = _Client()
    kw = asyncio.run(_open(client, ARGS))
    assert kw["extra_body"] == {"speed": "fast"}
    assert [c["_retries"] for c in client.calls] == [0]


def test_rate_limited_fast_request_falls_back_to_standard_speed():
    for err in (_refusal(RateLimitError, 429), _refusal(OverloadedError, 529)):
        client = _Client(refuse=err)
        kw = asyncio.run(_open(client, ARGS))
        assert "extra_body" not in kw
        assert [("extra_body" in c, c["_retries"]) for c in client.calls] == [(True, 0), (False, 2)]


def test_standard_request_is_untouched():
    client = _Client(refuse=_refusal(RateLimitError, 429))
    args = {k: v for k, v in ARGS.items() if k != "extra_body"}
    kw = asyncio.run(_open(client, args))
    assert "extra_body" not in kw and len(client.calls) == 1


def test_without_speed_keeps_other_extra_body_keys():
    out = engine._without_speed({"model": "m", "extra_body": {"speed": "fast", "other": 1}})
    assert out == {"model": "m", "extra_body": {"other": 1}}

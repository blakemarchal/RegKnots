"""2026-09-23 — synthesis model floor + per-model stream kwargs.

Blake: make Opus 5.5 the default answer model. The Haiku router still runs
(it is the off-topic gate), but its Haiku / Sonnet pick is lifted to the floor
right at the synthesis call. Sync tests driving asyncio.run().
"""
import asyncio
from uuid import uuid4

import pytest

import rag.engine as engine
from rag.engine import (
    _MAX_TOKENS, _OPUS_EFFORT_STREAM, _OPUS_MAX_TOKENS, _SONNET_EFFORT_STREAM,
    _apply_model_floor, _stream_kwargs,
)
from rag.models import RouteDecision

HAIKU, SONNET, OPUS = "claude-haiku-4-5-20251001", "claude-sonnet-5", "claude-opus-5-5"


def test_floor_lifts_lower_tiers_and_never_lowers():
    assert _apply_model_floor(HAIKU, OPUS) == OPUS
    assert _apply_model_floor(SONNET, OPUS) == OPUS
    assert _apply_model_floor(OPUS, OPUS) == OPUS
    assert _apply_model_floor(OPUS, SONNET) == OPUS      # a floor never lowers
    assert _apply_model_floor(HAIKU, SONNET) == SONNET
    assert _apply_model_floor(HAIKU, None) == HAIKU       # no floor = pure routing
    assert _apply_model_floor(HAIKU, "") == HAIKU
    assert _apply_model_floor("", OPUS) == ""             # off-topic short-circuit untouched


def test_stream_kwargs_per_model():
    assert _OPUS_EFFORT_STREAM == "low"
    assert _stream_kwargs(OPUS) == {
        "max_tokens": _OPUS_MAX_TOKENS, "output_config": {"effort": "low"},
    }
    sonnet = _stream_kwargs(SONNET)
    assert sonnet["max_tokens"] == _MAX_TOKENS
    assert sonnet.get("output_config") == (
        {"effort": _SONNET_EFFORT_STREAM} if _SONNET_EFFORT_STREAM else None
    )
    # Haiku 4.5 rejects `effort` — output_config must never reach it.
    assert _stream_kwargs(HAIKU) == {"max_tokens": _MAX_TOKENS}


class _Captured(BaseException):
    """Stops the engine at the synthesis call (not an Exception, so no fallback path catches it)."""


class _Pool:
    async def execute(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        return None


def _synthesis_kwargs(monkeypatch, route_model: str, floor: str | None) -> dict:
    seen: dict = {}

    async def route(query, client):
        return RouteDecision(score=1, model=route_model, is_off_topic=False)

    async def retrieve(**kw):
        return []

    class _Messages:
        def stream(self, **kw):
            seen.update(kw)
            raise _Captured()

    client = type("Client", (), {"messages": _Messages()})()
    monkeypatch.setattr(engine, "route_query", route)
    monkeypatch.setattr(engine, "retrieve_enhanced", retrieve)

    async def run():
        with pytest.raises(_Captured):
            async for _ in engine.chat_with_progress(
                query="how often are fire drills required", conversation_history=[],
                vessel_profile=None, pool=_Pool(), anthropic_client=client,
                openai_api_key="", conversation_id=uuid4(),
                query_rewrite_enabled=False, reranker_enabled=False,
                synthesis_model_floor=floor,
            ):
                pass

    asyncio.run(asyncio.wait_for(run(), timeout=10))
    return seen


def test_haiku_route_is_synthesized_on_the_opus_floor(monkeypatch):
    kw = _synthesis_kwargs(monkeypatch, HAIKU, OPUS)
    assert kw["model"] == OPUS
    assert kw["max_tokens"] == _OPUS_MAX_TOKENS
    assert kw["output_config"] == {"effort": "low"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}


def test_no_floor_keeps_the_routed_model(monkeypatch):
    kw = _synthesis_kwargs(monkeypatch, HAIKU, None)
    assert kw["model"] == HAIKU
    assert "output_config" not in kw


def test_chat_forwards_the_floor(monkeypatch):
    seen: dict = {}

    async def fake_stream(**kw):
        seen.update(kw)
        yield {"event": "done", "data": {
            "answer": "ok", "conversation_id": str(uuid4()), "model_used": OPUS,
        }}

    monkeypatch.setattr(engine, "chat_with_progress", fake_stream)
    resp = asyncio.run(engine.chat(
        query="q", conversation_history=[], vessel_profile=None, pool=_Pool(),
        anthropic_client=None, openai_api_key="", conversation_id=uuid4(),
        synthesis_model_floor=OPUS,
    ))
    assert seen["synthesis_model_floor"] == OPUS
    assert resp.model_used == OPUS

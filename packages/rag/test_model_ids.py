"""2026-09-28 — Sonnet 5 → Sonnet 5.5 and one setting for the small model.

Sync tests driving asyncio.run() so no pytest-asyncio config is needed.
"""
import asyncio
from types import SimpleNamespace

import rag.citation_oracle as citation_oracle
import rag.hedge_audit as hedge_audit
import rag.hedge_judge as hedge_judge
import rag.query_distill as query_distill
import rag.query_rewrite as query_rewrite
import rag.reranker as reranker
import rag.router as router
from rag.llm import (
    FALLBACK_BETA, SIDECAR_MODEL, create_json, messages_create, obj, small_call_kwargs,
    takes_server_fallback, STR,
)

SONNET_55 = "claude-sonnet-5-5"


def _resp(text="", stop_reason="end_turn", iterations=None, model=SONNET_55):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        stop_reason=stop_reason,
        model=model,
        usage=SimpleNamespace(iterations=iterations or []),
    )


class _Recorder:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _client(response):
    """A fake client with both the plain and the beta messages surface."""
    return SimpleNamespace(
        messages=_Recorder(response),
        beta=SimpleNamespace(messages=_Recorder(response)),
    )


# ── small model setting ──────────────────────────────────────────────────────

def test_sidecar_modules_share_one_setting():
    assert router.MODEL_MAP[1] == SIDECAR_MODEL
    for module_model in (
        query_distill.DISTILL_MODEL, query_rewrite._REWRITE_MODEL, reranker._RERANK_MODEL,
        hedge_judge._JUDGE_MODEL, citation_oracle._ORACLE_MODEL, hedge_audit._CLASSIFIER_MODEL,
    ):
        assert module_model == SIDECAR_MODEL


def test_small_call_kwargs_keeps_haiku_45_caps_and_guards_thinking_models():
    assert small_call_kwargs("claude-haiku-4-5-20251001", 10) == {"max_tokens": 10}
    assert small_call_kwargs("claude-haiku-4-5", 400) == {"max_tokens": 400}
    guarded = small_call_kwargs(SONNET_55, 10)
    assert guarded["max_tokens"] >= 2048
    assert guarded["output_config"] == {"effort": "low"}
    # A larger cap is never lowered.
    assert small_call_kwargs("claude-haiku-5-5", 8000)["max_tokens"] == 8000


# ── Sonnet 5.5 ───────────────────────────────────────────────────────────────

def test_router_scores_come_from_structured_output():
    assert router.MODEL_MAP[2] == SONNET_55
    c = _client(_resp('{"score": 2}'))
    assert asyncio.run(router._classify_once("q", c, SONNET_55)) == 2
    kw = c.beta.messages.kwargs          # Sonnet 5.5 goes through the fallback surface
    assert kw["max_tokens"] >= 2048
    assert kw["output_config"]["effort"] == "low"
    assert kw["output_config"]["format"]["schema"] == router._SCORE_SCHEMA

    haiku = _client(_resp('{"score": 1}'))
    assert asyncio.run(router._classify_once("q", haiku, "claude-haiku-4-5-20251001")) == 1
    assert haiku.messages.kwargs["max_tokens"] == 20
    assert "effort" not in haiku.messages.kwargs["output_config"]

    # Prose or a refusal is None (the caller's default-score path), never a
    # digit picked out of the text.
    prose = _client(_resp("The question is about 46 CFR 142"))
    assert asyncio.run(router._classify_once("q", prose, "claude-haiku-4-5-20251001")) is None
    refused = _client(_resp("", stop_reason="refusal"))
    assert asyncio.run(router._classify_once("q", refused, SONNET_55)) is None


def test_messages_create_adds_the_server_side_fallback_for_sonnet_55_only():
    assert takes_server_fallback(SONNET_55)
    assert not takes_server_fallback("claude-sonnet-5")
    assert not takes_server_fallback("claude-opus-5-5")

    c = _client(_resp("ok"))
    asyncio.run(messages_create(c, model=SONNET_55, max_tokens=5, messages=[]))
    assert c.messages.kwargs is None
    assert c.beta.messages.kwargs["fallbacks"] == "default"
    assert c.beta.messages.kwargs["betas"] == [FALLBACK_BETA]

    h = _client(_resp("ok"))
    asyncio.run(messages_create(h, model=SIDECAR_MODEL, max_tokens=5, messages=[]))
    assert h.beta.messages.kwargs is None
    assert "fallbacks" not in h.messages.kwargs


def test_messages_create_keeps_caller_betas():
    c = _client(_resp("ok"))
    asyncio.run(messages_create(c, model=SONNET_55, betas=["other-beta"], messages=[]))
    assert c.beta.messages.kwargs["betas"] == ["other-beta", FALLBACK_BETA]


def test_create_json_on_sonnet_55_goes_through_the_fallback():
    served = _resp('{"a": "x"}', iterations=[SimpleNamespace(type="fallback_message")],
                   model="claude-opus-4-8")
    c = _client(served)
    r = asyncio.run(create_json(c, schema=obj({"a": STR}), label="t", model=SONNET_55,
                                max_tokens=100, messages=[]))
    assert r.data == {"a": "x"}
    assert c.beta.messages.kwargs["output_config"]["format"]["type"] == "json_schema"

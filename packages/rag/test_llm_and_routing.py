"""2026-09-22 LLM surface upgrades — rag/llm.py helpers (U2/U3/U5/U7) and the
route-concurrent-with-retrieval change in engine.chat_with_progress (U1).

Sync tests driving asyncio.run() so no pytest-asyncio config is needed.
"""
import asyncio
import io
from types import SimpleNamespace
from uuid import uuid4

import pytest

import rag.engine as engine
from rag.llm import (
    INT, STR, arr, cached_system, create_json, enum, is_refusal, nullable, obj,
    parse_json_text, pdf_document_block, text_of,
)
from rag.models import RouteDecision


# ── text_of / refusal ────────────────────────────────────────────────────────

def _resp(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason)


def _t(text):
    return SimpleNamespace(type="text", text=text)


THINK = SimpleNamespace(type="thinking", thinking="")


def test_text_of_reads_by_block_type():
    assert text_of(_resp(THINK, _t("a"), THINK, _t("b"))) == "ab"
    assert text_of(_resp(THINK)) == ""
    assert text_of(SimpleNamespace(content=None)) == ""


def test_is_refusal():
    assert is_refusal(_resp(stop_reason="refusal"))
    assert not is_refusal(_resp(_t("x")))


# ── schema constructors ──────────────────────────────────────────────────────

def test_obj_is_strict_and_requires_all_by_default():
    s = obj({"a": STR, "b": INT})
    assert s["additionalProperties"] is False
    assert s["required"] == ["a", "b"]
    assert obj({"a": STR, "b": INT}, required=["a"])["required"] == ["a"]


def test_nullable_enum_arr_shapes():
    assert nullable(STR) == {"anyOf": [STR, {"type": "null"}]}
    assert enum("x", "y") == {"enum": ["x", "y"]}
    assert arr(INT) == {"type": "array", "items": INT}


def _walk(schema):
    yield schema
    for v in schema.get("properties", {}).values():
        yield from _walk(v)
    if "items" in schema:
        yield from _walk(schema["items"])
    for v in schema.get("anyOf", []):
        yield from _walk(v)


@pytest.mark.parametrize("mod_attr", [
    ("rag.reranker", "_RERANK_SCHEMA"),
    ("rag.query_rewrite", "_REWRITE_SCHEMA"),
    ("rag.hedge_judge", "_JUDGE_SCHEMA"),
    ("rag.hedge_audit", "_CLASSIFIER_SCHEMA"),
    ("rag.citation_oracle", "_ORACLE_SCHEMA"),
    ("rag.engine", "_ORACLE_SYNTHESIS_SCHEMA"),
])
def test_every_object_in_every_schema_is_closed(mod_attr):
    """Structured outputs reject an object without additionalProperties:false,
    and do not support numeric/length constraints."""
    import importlib
    schema = getattr(importlib.import_module(mod_attr[0]), mod_attr[1])
    for node in _walk(schema):
        if node.get("type") == "object":
            assert node.get("additionalProperties") is False
            assert set(node["required"]) <= set(node["properties"])
        for banned in ("minimum", "maximum", "minLength", "maxLength", "multipleOf"):
            assert banned not in node


# ── parse / create_json ──────────────────────────────────────────────────────

def test_parse_json_text():
    assert parse_json_text('{"a": 1}') == {"a": 1}
    assert parse_json_text('{"a": ') is None       # truncated
    assert parse_json_text("[1, 2]") is None        # not an object
    assert parse_json_text("") is None


class _FakeMessages:
    def __init__(self, response):
        self.response = response
        self.kwargs = None

    async def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _client(response):
    return SimpleNamespace(messages=_FakeMessages(response))


def test_create_json_returns_data_and_sends_format():
    c = _client(_resp(THINK, _t('{"verdict": "false_hedge"}')))
    r = asyncio.run(create_json(
        c, schema=obj({"verdict": STR}), label="t", model="m", max_tokens=10,
        output_config={"effort": "low"}, messages=[],
    ))
    assert r.data == {"verdict": "false_hedge"}
    cfg = c.messages.kwargs["output_config"]
    assert cfg["effort"] == "low"                          # merged, not replaced
    assert cfg["format"]["type"] == "json_schema"
    assert c.messages.kwargs["model"] == "m"


def test_create_json_refusal_and_truncation_yield_no_data():
    refused = asyncio.run(create_json(
        _client(_resp(stop_reason="refusal")), schema=obj({}), label="t", messages=[]))
    assert refused.data is None and refused.stop_reason == "refusal"
    cut = asyncio.run(create_json(
        _client(_resp(_t('{"scores": [{"index": 0'), stop_reason="max_tokens")),
        schema=obj({}), label="t", messages=[]))
    assert cut.data is None and cut.text.startswith('{"scores"')   # text kept for salvage


# ── caching / PDF ────────────────────────────────────────────────────────────

def test_cached_system_marks_the_block():
    [block] = cached_system("PROMPT")
    assert block == {"type": "text", "text": "PROMPT", "cache_control": {"type": "ephemeral"}}


def _pdf(pages):
    from pypdf import PdfWriter
    w = PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


def test_pdf_document_block_trims_to_max_pages():
    import base64
    from pypdf import PdfReader
    block = pdf_document_block(_pdf(5), max_pages=2)
    assert block["type"] == "document"
    assert block["source"]["media_type"] == "application/pdf"
    out = PdfReader(io.BytesIO(base64.b64decode(block["source"]["data"])))
    assert len(out.pages) == 2


def test_pdf_document_block_sends_unreadable_bytes_unchanged():
    import base64
    block = pdf_document_block(b"not a pdf", max_pages=2)
    assert base64.b64decode(block["source"]["data"]) == b"not a pdf"


# ── U1: route runs concurrently with retrieval ───────────────────────────────

class _Pool:
    async def execute(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        return None


def _stream(query="how often are fire drills required", **overrides):
    kw = dict(
        query=query, conversation_history=[], vessel_profile=None, pool=_Pool(),
        anthropic_client=None, openai_api_key="", conversation_id=uuid4(),
        query_rewrite_enabled=False, reranker_enabled=False,
    )
    kw.update(overrides)
    return engine.chat_with_progress(**kw)


def test_off_topic_cancels_in_flight_retrieval(monkeypatch):
    state = {"started": False, "cancelled": False}

    async def slow_retrieve(**kw):
        state["started"] = True
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise
        return []

    async def route(query, client):
        await asyncio.sleep(0.05)          # let retrieval start first
        return RouteDecision(score=0, model="", is_off_topic=True)

    async def off_topic(**kw):
        yield {"event": "done", "data": {"answer": "off-topic"}}

    monkeypatch.setattr(engine, "retrieve_enhanced", slow_retrieve)
    monkeypatch.setattr(engine, "route_query", route)
    monkeypatch.setattr(engine, "_handle_off_topic_stream", off_topic)

    async def run():
        return [e async for e in _stream()]

    events = asyncio.run(asyncio.wait_for(run(), timeout=5))
    assert events[-1] == {"event": "done", "data": {"answer": "off-topic"}}
    assert state["started"] and state["cancelled"]
    assert not any(e.get("event") == "status" and "Searching" in str(e.get("data")) for e in events)


def test_client_disconnect_during_routing_cancels_both_tasks(monkeypatch):
    state = {"retrieval_cancelled": False, "route_cancelled": False}

    async def slow_retrieve(**kw):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["retrieval_cancelled"] = True
            raise

    async def slow_route(query, client):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            state["route_cancelled"] = True
            raise

    monkeypatch.setattr(engine, "retrieve_enhanced", slow_retrieve)
    monkeypatch.setattr(engine, "route_query", slow_route)

    async def run():
        gen = _stream()
        first = await gen.__anext__()                       # "Analyzing…"
        assert first["event"] == "status"
        consumer = asyncio.ensure_future(gen.__anext__())   # now awaiting the route
        await asyncio.sleep(0.05)
        consumer.cancel()                                   # the client goes away
        with pytest.raises(asyncio.CancelledError):
            await consumer
        await asyncio.sleep(0.05)

    asyncio.run(asyncio.wait_for(run(), timeout=5))
    assert state["route_cancelled"] and state["retrieval_cancelled"]

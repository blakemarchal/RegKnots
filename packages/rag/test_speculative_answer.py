"""2026-10-17 — the answer call starts while the coverage check runs
(rag.engine._SpeculativeAnswer). It is used only when coverage and web
research leave the library text unchanged, so the answer request is the same
one the engine would have sent afterwards; otherwise it is cancelled."""
import asyncio
from uuid import uuid4

import rag.coverage as coverage_mod
import rag.engine as engine
import rag.web_research as web_mod
from rag.coverage import Coverage, MissingItem
from rag.models import RouteDecision

OPUS = "claude-opus-5-5"


class _Pool:
    async def execute(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        return None


class _Final:
    class usage:
        input_tokens = 100
        output_tokens = 20

    stop_reason = "end_turn"


class _Client:
    """messages.stream(**kw): records each call, streams `chunks` slowly, notes an early close."""

    def __init__(self, chunks=("Answer ", "text.")):
        self.calls: list[dict] = []
        self.chunks = chunks
        outer = self

        class _Stream:
            def __init__(self, kw):
                self.kw = kw

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                self.kw["_closed_by"] = exc_type.__name__ if exc_type else "done"
                return False

            @property
            async def text_stream(self):
                for c in outer.chunks:
                    await asyncio.sleep(0.1)    # slower than coverage + research, so a cancel lands mid-answer
                    yield c

            async def get_final_message(self):
                return _Final()

        class _Messages:
            def stream(self, **kw):
                kw = dict(kw)
                kw["_at"] = len(outer.events)
                outer.calls.append(kw)
                return _Stream(kw)

        self.messages = _Messages()
        self.events: list[str] = []

    def with_options(self, **kw):                # fast mode turns the SDK's retries off
        return self


def _run(monkeypatch, *, missing=(), web_block=None, speculative=True, stop_at="Verifying citations…",
         fast=False):
    client = _Client()

    async def route(query, c, context=None):
        return RouteDecision(score=1, model=OPUS, is_off_topic=False)

    async def retrieve(**kw):
        return []

    async def check_coverage(c, **kw):
        await asyncio.sleep(0.05)               # the speculative call starts meanwhile
        client.events.append("coverage")
        return Coverage("partial" if missing else "full", [MissingItem(m, m) for m in missing])

    async def allowed(*a, **k):
        return True

    async def research(c, items, **kw):
        await asyncio.sleep(0.05)
        client.events.append("research")
        return []

    monkeypatch.setattr(engine, "route_query", route)
    monkeypatch.setattr(engine, "retrieve_enhanced", retrieve)
    monkeypatch.setattr(engine, "_web_research_allowed", allowed)
    monkeypatch.setattr(coverage_mod, "check_coverage", check_coverage)
    monkeypatch.setattr(web_mod, "research", research)
    monkeypatch.setattr(web_mod, "format_block", lambda findings: web_block)

    out: list[dict] = []

    async def go():
        agen = engine.chat_with_progress(
            query="how often are fire drills required", conversation_history=[],
            vessel_profile=None, pool=_Pool(), anthropic_client=client,
            openai_api_key="", conversation_id=uuid4(),
            query_rewrite_enabled=False, reranker_enabled=False,
            synthesis_model_floor=OPUS, pipeline_v2_enabled=True,
            speculative_answer_enabled=speculative,
            synthesis_fast_mode=fast,
        )
        async for ev in agen:
            out.append(ev)
            if ev["event"] == "status" and ev["data"] == stop_at:
                break
        await agen.aclose()                     # what the server does when the client goes
        await asyncio.sleep(0.1)                # let a cancelled call finish closing

    asyncio.run(asyncio.wait_for(go(), timeout=10))
    return client, out


def _deltas(events):
    return "".join(e["data"] for e in events if e["event"] == "delta")


def test_full_coverage_uses_the_call_started_before_it(monkeypatch):
    client, events = _run(monkeypatch)
    assert len(client.calls) == 1
    assert client.calls[0]["_at"] == 0                    # started before coverage returned
    assert _deltas(events) == "Answer text."
    statuses = [e["data"] for e in events if e["event"] == "status"]
    assert statuses.index("Consulting compliance engine…") < len(statuses) - 1


def test_web_findings_discard_it_and_write_with_them(monkeypatch):
    client, events = _run(monkeypatch, missing=["drill interval"], web_block="WEB FINDINGS: x")
    assert len(client.calls) == 2
    assert client.calls[0]["_closed_by"] == "CancelledError"
    first, second = (str(c["messages"]) for c in client.calls)
    assert "WEB FINDINGS: x" not in first and "WEB FINDINGS: x" in second
    assert _deltas(events) == "Answer text."


def test_research_that_finds_nothing_keeps_it(monkeypatch):
    client, events = _run(monkeypatch, missing=["drill interval"], web_block=None)
    assert len(client.calls) == 1 and client.events == ["coverage", "research"]
    assert _deltas(events) == "Answer text."


def test_switched_off_the_call_waits_for_coverage(monkeypatch):
    client, events = _run(monkeypatch, speculative=False)
    assert len(client.calls) == 1 and client.calls[0]["_at"] == 1    # after coverage
    assert _deltas(events) == "Answer text."


def test_a_client_that_leaves_during_research_cancels_it(monkeypatch):
    client, events = _run(monkeypatch, missing=["drill interval"], web_block="WEB FINDINGS: x",
                          stop_at="Checking Coast Guard, IMO and other official sources…")
    assert len(client.calls) == 1 and client.calls[0]["_closed_by"] == "CancelledError"
    assert _deltas(events) == ""


def test_fast_mode_asks_for_speed_on_both_paths(monkeypatch):
    for speculative in (True, False):
        client, events = _run(monkeypatch, speculative=speculative, fast=True)
        assert [c.get("extra_body") for c in client.calls] == [{"speed": "fast"}]
        assert _deltas(events) == "Answer text."
    client, _ = _run(monkeypatch)
    assert "extra_body" not in client.calls[0]

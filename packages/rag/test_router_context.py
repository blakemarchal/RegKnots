"""2026-10-05 — the off-topic check sees the conversation for a follow-up.

A crew member asked for an SMS emergency procedure, then wrote "pls improve"
and "can u read this"; both classifier passes saw only those words and the
user got the off-topic refusal twice (2026-10-06)."""
import asyncio
from uuid import uuid4

from rag import engine, router
from rag.followup import router_context
from rag.models import ChatMessage
from rag.router import RouteDecision

SMS = "can you make me a emergency procedure SMS on ship"


def _history(*turns):
    return [ChatMessage(role=r, content=c) for r, c in turns]


def test_router_context_is_the_first_question_and_the_previous_message():
    assert router_context([]) is None
    one = _history(("user", SMS), ("assistant", "# Emergency Procedures Template ..."))
    assert router_context(one) == f"First question: {SMS}"
    two = _history(("user", SMS), ("assistant", "template"), ("user", "pls improve"), ("assistant", "refusal"))
    assert router_context(two) == f"First question: {SMS}\nPrevious message: pls improve"
    long = _history(("user", "x" * 1000))
    assert router_context(long, max_chars=50) == "First question: " + "x" * 50


def test_the_classifier_prompt_carries_the_context():
    content = router._classifier_content("pls improve", f"First question: {SMS}")
    assert content.endswith(f"Earlier in this conversation:\nFirst question: {SMS}\n\nQuestion: pls improve")
    assert router._classifier_content("what is SOLAS", None).endswith("\n\nQuestion: what is SOLAS")
    assert "scores like the conversation" in router.CLASSIFIER_PROMPT


def test_both_classifier_passes_get_the_context(monkeypatch):
    calls = []

    async def classify(query, client, model, context=None):
        calls.append((query, model, context))
        return 0 if len(calls) == 1 else 2       # Haiku says 0, Sonnet overrides

    monkeypatch.setattr(router, "_classify_once", classify)
    decision = asyncio.run(router.route_query("pls improve", None, context=f"First question: {SMS}"))
    assert not decision.is_off_topic and decision.score == 2
    assert [c[2] for c in calls] == [f"First question: {SMS}"] * 2


class _Pool:
    async def execute(self, *a, **k):
        return None

    async def fetchval(self, *a, **k):
        return None


def test_the_engine_routes_a_follow_up_with_the_conversation(monkeypatch):
    seen = {}

    async def route(query, client, context=None):
        seen["query"], seen["context"] = query, context
        return RouteDecision(score=0, model="", is_off_topic=True)

    async def retrieve(**kw):
        await asyncio.sleep(30)

    async def off_topic(**kw):
        yield {"event": "done", "data": {"answer": "off-topic"}}

    monkeypatch.setattr(engine, "route_query", route)
    monkeypatch.setattr(engine, "retrieve_enhanced", retrieve)
    monkeypatch.setattr(engine, "_handle_off_topic_stream", off_topic)
    history = _history(("user", SMS), ("assistant", "template"), ("user", "pls improve"), ("assistant", "refusal"))

    async def run():
        gen = engine.chat_with_progress(
            query="can u read this", conversation_history=history, vessel_profile=None, pool=_Pool(),
            anthropic_client=None, openai_api_key="", conversation_id=uuid4(),
            query_rewrite_enabled=False, reranker_enabled=False,
        )
        return [e async for e in gen]

    asyncio.run(asyncio.wait_for(run(), timeout=5))
    assert seen == {"query": "can u read this", "context": f"First question: {SMS}\nPrevious message: pls improve"}

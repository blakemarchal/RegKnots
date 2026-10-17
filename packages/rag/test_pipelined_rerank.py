"""2026-10-17 — pipelined rerank in retrieve_enhanced: the primary search's
candidates are scored while the reformulation searches run, then only the
candidates the reformulations add; one stable sort over the merged pool."""
import asyncio

import rag.query_rewrite as QR
import rag.reranker as RR
import rag.retriever as R
from rag.query_rewrite import QueryRewrite

ROWS = {
    "q": [(1, 0.90), (2, 0.80), (3, 0.70)],
    "r1": [(3, 0.75), (4, 0.85)],
    "r2": [(5, 0.60)],
}
SCORES = {1: 2, 2: 5, 3: 1, 4: 5, 5: 0}


def _row(i, sim):
    return {"id": i, "source": "cfr_46", "section_number": f"46 CFR {i}", "section_title": "t",
            "full_text": "x", "similarity": sim}


def _setup(monkeypatch, fail_first=False):
    calls: list[list[int]] = []
    events: list[str] = []

    async def retrieve(query, **kw):
        await asyncio.sleep(0.01 if query == "q" else 0.05)
        events.append(f"search {query}")
        return [_row(i, s) for i, s in ROWS[query]]

    async def rewrite_query(query, anthropic_client):
        await asyncio.sleep(0.03)
        events.append("rewrite")
        return QueryRewrite(original=query, reformulations=["r1", "r2"])

    async def score_chunks(query, chunks, client, per_chunk_chars=1500):
        calls.append([c["id"] for c in chunks])
        events.append(f"score {[c['id'] for c in chunks]}")
        if fail_first and len(calls) == 1:
            return None
        return {i: SCORES[c["id"]] for i, c in enumerate(chunks)}

    monkeypatch.setattr(R, "retrieve", retrieve)
    monkeypatch.setattr(QR, "rewrite_query", rewrite_query)
    monkeypatch.setattr(RR, "score_chunks", score_chunks)
    monkeypatch.setattr(R, "_PIPELINED_RERANK", True)

    out = asyncio.run(R.retrieve_enhanced(
        "q", pool=None, openai_api_key="", anthropic_client=object(), limit=8,
        query_rewrite_enabled=True, reranker_enabled=True, rerank_pool_size=30,
    ))
    return out, calls, events


def test_primary_is_scored_while_the_reformulations_search(monkeypatch):
    out, calls, events = _setup(monkeypatch)
    assert calls == [[1, 2, 3], [4, 5]]                    # primary first, then only the new ones
    assert events.index("score [1, 2, 3]") < events.index("search r1")
    # merged by similarity: 1 .90, 4 .85, 2 .80, 3 .75, 5 .60; stable sort by score
    assert [c["id"] for c in out] == [4, 2, 1, 3, 5]
    assert [c["_rerank_score"] for c in out] == [5, 5, 2, 1, 0]


def test_a_failed_primary_scoring_falls_back_to_one_call(monkeypatch):
    out, calls, _ = _setup(monkeypatch, fail_first=True)
    assert calls[0] == [1, 2, 3] and calls[1] == [1, 4, 2, 3, 5]    # the whole pool, in merged order
    assert [c["id"] for c in out] == [4, 2, 1, 3, 5]


def test_switched_off_scores_the_merged_pool_once(monkeypatch):
    calls: list[list[int]] = []

    async def retrieve(query, **kw):
        return [_row(i, s) for i, s in ROWS[query]]

    async def rewrite_query(query, anthropic_client):
        return QueryRewrite(original=query, reformulations=["r1", "r2"])

    async def score_chunks(query, chunks, client, per_chunk_chars=1500):
        calls.append([c["id"] for c in chunks])
        return {i: SCORES[c["id"]] for i, c in enumerate(chunks)}

    monkeypatch.setattr(R, "retrieve", retrieve)
    monkeypatch.setattr(QR, "rewrite_query", rewrite_query)
    monkeypatch.setattr(RR, "score_chunks", score_chunks)
    monkeypatch.setattr(R, "_PIPELINED_RERANK", False)
    out = asyncio.run(R.retrieve_enhanced(
        "q", pool=None, openai_api_key="", anthropic_client=object(), limit=8,
        query_rewrite_enabled=True, reranker_enabled=True, rerank_pool_size=30,
    ))
    assert calls == [[1, 4, 2, 3, 5]]
    assert [c["id"] for c in out] == [4, 2, 1, 3, 5]

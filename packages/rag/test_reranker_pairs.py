"""2026-09-25 — reranker output as [index, score] pairs (validated 2026-09-24)."""
import asyncio
from types import SimpleNamespace

import rag.reranker as RR


def _chunks(n):
    return [{"id": i, "section_number": f"s{i}", "full_text": "t"} for i in range(n)]


def _fake(data, seen):
    async def fake(client, **kw):
        seen.update(kw)
        return SimpleNamespace(data=data, text="")
    return fake


def test_pairs_are_parsed_and_ranked(monkeypatch):
    seen = {}
    monkeypatch.setattr(RR, "create_json", _fake({"scores": [[0, 2], [1, 5], [2, 4], [3, 9], ["x", 1]]}, seen))
    out = asyncio.run(RR.rerank_chunks("q", _chunks(4), anthropic_client=object()))
    assert seen["schema"] == {"type": "object", "additionalProperties": False, "required": ["scores"],
                              "properties": {"scores": {"type": "array", "items": {
                                  "type": "array", "items": {"type": "integer"}}}}}
    assert "[index, score]" in seen["system"]
    assert [(c["id"], c["_rerank_score"]) for c in out] == [(1, 5), (3, 5), (2, 4), (0, 2)]


def test_object_form_still_parses(monkeypatch):
    monkeypatch.setattr(RR, "create_json", _fake({"scores": [{"index": 2, "score": 5}]}, {}))
    out = asyncio.run(RR.rerank_chunks("q", _chunks(3), anthropic_client=object()))
    assert [c["id"] for c in out] == [2, 0, 1]

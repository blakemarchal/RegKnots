"""2026-10-08 — whole-section reading (rag.sections)."""
import asyncio
import re

import pytest

from rag import sections as S


def _row(src, sec, idx, text):
    return {"id": f"{sec}#{idx}", "source": src, "section_number": sec, "section_title": "t",
            "full_text": text, "chunk_index": idx}


REG23 = [_row("solas", "SOLAS Ch.V Reg.23", i, f"paragraph block {i} " * 60) for i in range(4)]
CFR = [_row("cfr_46", "46 CFR 163.003-13", i, f"construction {i} " * 60) for i in range(2)]
BIG = [_row("cfr_46", "46 CFR 999.1", i, f"long text {i} " * 400) for i in range(10)]
DB = REG23 + CFR + BIG


class Pool:
    def __init__(self, rows=DB, fail=False):
        self.rows, self.fail = rows, fail

    async def fetch(self, sql, *args):
        if self.fail:
            raise RuntimeError("db down")
        if "DISTINCT source, section_number" in sql:
            return [{"source": s, "section_number": n}
                    for s, n in dict.fromkeys((r["source"], r["section_number"]) for r in self.rows if r["section_number"] in args[0])]
        keys = set(zip(args[0], args[1]))
        mine = [r for r in self.rows if (r["source"], r["section_number"]) in keys]
        if "count(*)" in sql:
            counts = {}
            for r in mine:
                counts[(r["source"], r["section_number"])] = counts.get((r["source"], r["section_number"]), 0) + 1
            return [{"source": k[0], "section_number": k[1], "n": n} for k, n in counts.items()]
        return sorted(mine, key=lambda r: (r["source"], r["section_number"], r["chunk_index"]))


def _retrieved(row, sim):
    return {k: row[k] for k in ("id", "source", "section_number", "section_title", "full_text")} | {"similarity": sim}


def run(chunks, query="pilot ladder", pool=None, budget=S.CONTEXT_TOKENS):
    return asyncio.run(S.expand_sections(pool or Pool(), chunks, query, budget=budget))


def test_a_section_is_read_whole_in_document_order():
    # the Captain's case: Reg.23's chunks 0-2 retrieved, out of order; chunk 3 (paragraphs 4-8) missing
    chunks = [_retrieved(REG23[2], 0.9), _retrieved(CFR[0], 0.8), _retrieved(REG23[0], 0.7), _retrieved(REG23[1], 0.6)]
    out = run(chunks)
    assert [c["id"] for c in out] == [r["id"] for r in REG23] + [CFR[0]["id"], CFR[1]["id"]]
    added = [c for c in out if c.get("_expanded")]
    assert {c["id"] for c in added} == {REG23[3]["id"], CFR[1]["id"]}
    assert added[0]["similarity"] == 0.9                      # the section's best similarity
    assert out[0] is chunks[2]                                # retrieved chunks are the same objects


def test_a_named_section_goes_first_even_if_retrieval_missed_it():
    out = run([_retrieved(CFR[0], 0.8)], query="Solas ch v reg 23 pilot ladder")
    assert [c["section_number"] for c in out[:4]] == ["SOLAS Ch.V Reg.23"] * 4
    assert out[4]["id"] == CFR[0]["id"]


def test_a_long_section_keeps_retrieved_chunks_and_neighbours():
    out = run([_retrieved(BIG[5], 0.8)])
    assert [c["id"] for c in out] == [BIG[4]["id"], BIG[5]["id"], BIG[6]["id"]]


def test_siblings_never_displace_retrieved_chunks():
    chunks = [_retrieved(REG23[0], 0.9), _retrieved(CFR[0], 0.8)]
    tight = sum(S._tokens(c["full_text"]) for c in chunks) + S._tokens(REG23[1]["full_text"])
    out = run(chunks, budget=tight)
    ids = [c["id"] for c in out]
    assert REG23[0]["id"] in ids and CFR[0]["id"] in ids     # both retrieved chunks kept
    assert ids.count(REG23[1]["id"]) == 1 and REG23[2]["id"] not in ids   # budget fits one sibling


def test_failure_returns_the_retrieved_chunks():
    chunks = [_retrieved(CFR[0], 0.8)]
    assert run(chunks, pool=Pool(fail=True)) is chunks


def test_build_context_takes_the_larger_budget():
    from rag.context import build_context
    chunks = [_retrieved(r, 0.5) for r in BIG]
    small, _ = build_context(chunks)
    large, _ = build_context(chunks, max_tokens=S.CONTEXT_TOKENS)
    assert len(re.findall(r"\[SOURCE:", large)) > len(re.findall(r"\[SOURCE:", small))


def test_engine_carries_the_flags():
    import inspect

    import rag.engine as E
    for fn in (E.chat, E.chat_with_progress):
        params = inspect.signature(fn).parameters
        assert params["whole_sections_enabled"].default is False
        assert params["provenance_prompt_enabled"].default is False

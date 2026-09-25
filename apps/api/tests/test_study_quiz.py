"""2026-09-23 — quiz generation on Sonnet 5 (audit U10) + case-insensitive
citation verification (every COLREGs quiz showed 0% verified).

Run from apps/api:
    uv run --extra dev python -m pytest tests -q
"""
import asyncio
import importlib
import re
from pathlib import Path

S = importlib.import_module("app.routers.study")


def test_quiz_runs_on_sonnet_with_pinned_effort_and_thinking_headroom():
    assert S._QUIZ_MODEL == "claude-sonnet-5"
    assert S._QUIZ_EFFORT == "high"
    # Sonnet 5 thinks adaptively and thinking counts toward max_tokens; a
    # 10-question quiz measured up to 5,055 output tokens at `high`.
    assert S._QUIZ_MAX_TOKENS >= 16000
    src = Path(S.__file__).read_text(encoding="utf-8")
    call = re.search(r'label="study quiz",(.*?)\)', src, re.S)
    assert call and 'output_config={"effort": _QUIZ_EFFORT}' in call.group(1)


class _Pool:
    """Answers the verifier's query from an in-memory list of section_numbers."""

    def __init__(self, corpus):
        self.corpus = corpus
        self.sql = ""

    async def fetch(self, sql, bases):
        self.sql = sql
        return [{"section_number": s.lower()} for s in self.corpus if s.lower() in bases]


def test_verify_citations_ignores_case_and_subsections():
    pool = _Pool(["COLREGS Rule 13", "46 CFR 199.180"])
    got = asyncio.run(S._verify_citations(
        pool, ["COLREGs Rule 13(b)", "46 CFR 199.180(a)(2)", "46 CFR 999.99"],
    ))
    assert got == {
        "COLREGs Rule 13(b)": True,
        "46 CFR 199.180(a)(2)": True,
        "46 CFR 999.99": False,
    }
    assert "lower(section_number)" in pool.sql


def test_exam_bank_context_uses_a_source_restricted_vector_search(monkeypatch):
    """2026-09-24 — was a whole-topic ILIKE: multi-word topics got 0 exam chunks."""
    import rag.retriever as R

    calls = []

    async def fake_retrieve(**kw):
        calls.append(kw)
        if kw.get("sources") == ["nmc_exam_bank"]:
            return [
                {"source": "nmc_exam_bank", "section_number": "Q103", "section_title": "Deck Safety", "full_text": "a"},
                {"source": "cfr_46", "section_number": "46 CFR 199.180", "section_title": "", "full_text": "b"},
                {"source": "nmc_exam_bank", "section_number": "Q104", "section_title": "Deck Safety", "full_text": "c"},
            ]
        return [{"source": "cfr_46", "section_number": "46 CFR 199.180", "section_title": "", "full_text": "b"}]

    async def fake_pool():
        return object()

    monkeypatch.setattr(R, "retrieve", fake_retrieve)
    monkeypatch.setattr(S, "get_pool", fake_pool)
    exam, corpus = asyncio.run(S._retrieve_for_topic("COLREGs Rule 13 overtaking", k_exam_bank=4))
    assert [c["section_number"] for c in exam] == ["Q103", "Q104"]   # other sources filtered out
    assert calls[0]["sources"] == ["nmc_exam_bank"] and calls[0]["query"] == "COLREGs Rule 13 overtaking"
    assert [c["section_number"] for c in corpus] == ["46 CFR 199.180"]


def test_verify_citations_empty_inputs():
    assert asyncio.run(S._verify_citations(_Pool([]), [])) == {}
    assert asyncio.run(S._verify_citations(_Pool([]), ["", ""])) == {"": False}

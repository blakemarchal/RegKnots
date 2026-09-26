"""2026-09-26 — MARPOL regulation citations resolve to the exact section.

"MARPOL Annex VI Regulation 14" used to become two text searches, "Annex VI"
and "Regulation 14", over every source; each returned the first 5 matching
rows in storage order and ranked them above every vector hit. The corpus now
names per-regulation sections "MARPOL Annex VI Reg.14".
"""
import asyncio

import pytest

import rag.retriever as R


@pytest.mark.parametrize("query,expected", [
    ("MARPOL Annex VI Regulation 14", [("VI", "14")]),
    ("What does MARPOL Annex VI Regulation 14.1 say about the 0.50% cap?", [("VI", "14")]),
    ("MARPOL Annex I, reg. 12A oil fuel tank protection", [("I", "12A")]),
    ("MARPOL 73/78 Annex V Reg 4", [("V", "4")]),
    ("marpol annex iv regulation 11 sewage discharge", [("IV", "11")]),
    ("regulation 13 of MARPOL Annex VI", [("VI", "13")]),
    ("Annex V Regulation 7 exceptions", [("V", "7")]),
    ("regulation 17 of Annex I oil record book", [("I", "17")]),
    ("compare MARPOL Annex VI Regulation 13 and MARPOL Annex VI Reg. 14", [("VI", "13"), ("VI", "14")]),
    ("MARPOL: what does Annex II Regulation 13 require?", [("II", "13")]),
])
def test_citation_forms(query, expected):
    assert R._marpol_citations(query) == expected


@pytest.mark.parametrize("query", [
    "What are the MARPOL Annex VI requirements for ECAs?",
    "latest MARPOL Annex VI amendment",
    "Load Line Convention Annex I Regulation 22 freeing ports",   # not MARPOL's Annex I
    "33 CFR 151 and Annex V Regulation 4",                        # bare form, another instrument named
    "STCW Regulation II/1 officer in charge",
    "SOLAS III/20",
])
def test_non_citations(query):
    assert R._marpol_citations(query) == []


def _marpol_ids(query):
    return [i for i in R._extract_identifiers(query) if i["type"].startswith("marpol")]


def test_regulation_becomes_an_exact_section_identifier_and_nothing_else():
    assert _marpol_ids("MARPOL Annex VI Regulation 14 sulphur limit") == [{
        "type": "marpol_reg",
        "value": "MARPOL Annex VI Reg.14",
        "pattern": "MARPOL Annex VI Reg.14",
        "section_number": "MARPOL Annex VI Reg.14",
        "source_filter": ("marpol",),
    }]


def test_an_annex_without_a_regulation_searches_within_that_annex():
    named = _marpol_ids("MARPOL Annex V garbage record book")
    assert named == [{
        "type": "marpol_annex",
        "value": "MARPOL Annex V",
        "pattern": "MARPOL Annex V",
        "section_prefix": "MARPOL Annex V ",
        "source_filter": ("marpol",),
    }]
    bare = _marpol_ids("What are the annex V exemptions for throwing plastic overboard")
    assert [(i["type"], i["section_prefix"]) for i in bare] == [("marpol_annex_implicit", "MARPOL Annex V ")]
    assert _marpol_ids("Load Line Convention Annex I freeboard") == []
    # an annex that has a cited regulation gets no annex-wide search
    assert [i["type"] for i in _marpol_ids("MARPOL Annex I Reg.17 and MARPOL Annex V")] == [
        "marpol_reg", "marpol_annex"]


class _CapturePool:
    def __init__(self):
        self.calls = []

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return []


def test_annex_search_sql_is_a_prefix_ranked_by_the_query_vector():
    pool = _CapturePool()
    asyncio.run(R._identifier_search(R._extract_identifiers("MARPOL Annex V garbage"), pool,
                                     allowed_jurisdictions=["intl", "us"], query_vec="[0.1]"))
    sql, args = pool.calls[0]
    assert "section_number LIKE $1" in sql and "ORDER BY embedding <=> $5::vector" in sql
    # "MARPOL Annex V %" cannot match "MARPOL Annex VI Reg.1"
    assert args == ("MARPOL Annex V %", 5, ["marpol"], ["intl", "us"], "[0.1]")
    pool = _CapturePool()
    asyncio.run(R._identifier_search(R._extract_identifiers("MARPOL Annex VI Regulation 99"), pool))
    assert len(pool.calls) == 1        # no such regulation: no fallback text search

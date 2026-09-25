"""2026-09-25 — SOLAS regulation citations resolve to the exact section.

The Captain's 2026-09-23 question "SOLAS Chapter III, Part B, Section I,
Regulation 20" matched no identifier (the old pattern needed a hyphenated
chapter and searched full_text for the chapter string alone), so the answer
said Reg.20's text had not been retrieved. The corpus names per-Regulation
sections "SOLAS Ch.III Reg.20".
"""
import asyncio

import pytest

import rag.retriever as R


@pytest.mark.parametrize("query,expected", [
    ("SOLAS Chapter III, Part B, Section I, Regulation 20", [("III", "20")]),
    ("SOLAS Chapter III, Part B, Section I, Regulation 20 life boat lowering", [("III", "20")]),
    ("SOLAS III/20 weekly and monthly LSA inspections", [("III", "20")]),
    ("liferaft servicing interval SOLAS III/20.8", [("III", "20")]),
    ("SOLAS Ch.III Reg.20", [("III", "20")]),
    ("what does SOLAS Ch. III, Reg. 20 say", [("III", "20")]),
    ("SOLAS Ch.III/19 drills", [("III", "19")]),
    ("SOLAS regulation II-2/10.2 fire mains", [("II-2", "10")]),
    ("SOLAS II-1/3-9 embarkation", [("II-1", "3-9")]),
    ("per Regulation III/20 of SOLAS", [("III", "20")]),
    ("regulation 19 of SOLAS chapter III", [("III", "19")]),
    ("SOLAS chapter 3 regulation 19", [("III", "19")]),
    ("SOLAS 1974 Chapter V Regulation 19", [("V", "19")]),
    ("compare SOLAS III/19 and SOLAS III/20", [("III", "19"), ("III", "20")]),
])
def test_citation_forms(query, expected):
    assert R._solas_citations(query) == expected


@pytest.mark.parametrize("query", [
    "What are the SOLAS requirements for fire detection on cargo ships?",
    "SOLAS regulations for lifeboats",
    "SOLAS Chapter III requirements",
    "SOLAS 74/88 amendments",
    "STCW Regulation II/1 officer in charge",
])
def test_non_citations(query):
    assert R._solas_citations(query) == []


def _solas_ids(query):
    return [i for i in R._extract_identifiers(query) if i["type"].startswith("solas")]


def test_regulation_citation_becomes_exact_section_identifier():
    ids = _solas_ids("SOLAS Chapter III, Part B, Section I, Regulation 20")
    assert ids == [{
        "type": "solas_reg",
        "value": "SOLAS Ch.III Reg.20",
        "pattern": "SOLAS Ch.III Reg.20",
        "section_number": "SOLAS Ch.III Reg.20",
        "source_filter": ("solas",),
    }]


@pytest.mark.parametrize("query", [
    "SOLAS II-2 fire detection",
    "SOLAS Ch.II-2 fire detection",
    "SOLAS Chapter III lifeboat drills",
    "SOLAS Ch.V bridge navigational watch alarm",
    "is it SOLAS I think or MARPOL",
    "What are the SOLAS requirements for lifeboats?",
])
def test_chapter_only_citation_adds_no_identifier(query):
    # the old chapter identifier returned 5 arbitrary chunks containing the
    # chapter string; a within-chapter search is held back until the SOLAS
    # re-ingest (the "SOLAS Ch.II-2 " rows are stale Part-level ones)
    assert _solas_ids(query) == []


def test_regulation_with_chapter_context():
    ids = _solas_ids("SOLAS Ch.II-2 Reg.10 fire main capacity")
    assert [i["value"] for i in ids] == ["SOLAS Ch.II-2 Reg.10"]
    assert _solas_ids("SOLAS Chapter III, Part B, Section I, Regulation 20")[0]["type"] == "solas_reg"


def _cfr_ids(query):
    return [i for i in R._extract_identifiers(query) if i["type"].startswith("cfr")]


def test_cfr_section_resolves_to_the_section():
    assert _cfr_ids("what does 46 CFR 199.180 require for drills.") == [{
        "type": "cfr_section",
        "value": "46 CFR 199.180",
        "pattern": "199.180",
        "section_number": "46 CFR 199.180",
        "source_filter": ("cfr_46",),
        "fallback_pattern": "199.180",
    }]
    assert _cfr_ids("46 CFR 35.10-5 fire drills")[0]["section_number"] == "46 CFR 35.10-5"
    # sentence-final period is not part of the section
    assert _cfr_ids("See 33 CFR 155.1050.")[0]["section_number"] == "33 CFR 155.1050"


def test_cfr_part_searches_within_the_part():
    assert _cfr_ids("33 CFR 138 certificate of financial responsibility") == [{
        "type": "cfr_part",
        "value": "33 CFR 138",
        "pattern": "138",
        "section_prefix": "33 CFR 138.",
        "source_filter": ("cfr_33",),
    }]


def test_cfr_title_not_in_corpus():
    # a dotted section keeps the old text search; a bare part finds nothing
    assert _cfr_ids("29 CFR 1910.134 respirators") == [
        {"type": "cfr_section", "value": "29 CFR 1910.134", "pattern": "1910.134"}]
    assert _cfr_ids("29 CFR 1910 respirators") == []


class _CapturePool:
    def __init__(self, rows=(), text_rows=()):
        self.calls, self.rows, self.text_rows = [], list(rows), list(text_rows)

    async def fetch(self, sql, *args):
        self.calls.append((sql, args))
        return self.rows if "section_number" in sql.split("FROM regulations WHERE")[-1] else self.text_rows


def test_section_search_sql():
    ident = R._extract_identifiers("SOLAS III/20")
    pool = _CapturePool()
    asyncio.run(R._identifier_search(ident, pool, allowed_jurisdictions=["intl", "us"], query_vec="[0.1]"))
    sql, args = pool.calls[0]
    assert "WITH m AS MATERIALIZED" in sql and "ILIKE" not in sql
    assert "section_number = $1" in sql
    assert "source = ANY($3)" in sql and "jurisdictions && $4::text[]" in sql
    assert "FROM m ORDER BY embedding <=> $5::vector LIMIT $2" in sql
    assert args == ("SOLAS Ch.III Reg.20", 5, ["solas"], ["intl", "us"], "[0.1]")
    pool = _CapturePool()
    asyncio.run(R._identifier_search(ident, pool))
    assert pool.calls[0][0].endswith("ORDER BY section_number, chunk_index LIMIT $2")
    # a part or chapter is a prefix match
    pool = _CapturePool()
    asyncio.run(R._identifier_search(R._extract_identifiers("33 CFR 138 COFR"), pool, query_vec="[0.1]"))
    sql, args = pool.calls[0]
    assert "section_number LIKE $1" in sql and args[0] == "33 CFR 138.%" and args[2] == ["cfr_33"]
    # text identifiers are unchanged: substring search, no ordering
    pool = _CapturePool()
    asyncio.run(R._identifier_search(R._extract_identifiers("CG-835"), pool, query_vec="[0.1]"))
    sql, args = pool.calls[0]
    assert "full_text ~ $1" in sql and "ORDER BY" not in sql and len(args) == 2


def test_missing_section_falls_back_to_text_search():
    hit = {"id": "x", "source": "nvic", "section_number": "NVIC 01-01",
           "section_title": "", "full_text": "... 46 CFR 199.18 ...", "similarity": 0.0}
    pool = _CapturePool(rows=[], text_rows=[hit])
    out = asyncio.run(R._identifier_search(R._extract_identifiers("46 CFR 199.18"), pool, query_vec="[0.1]"))
    assert [c["id"] for c in out] == ["x"]
    assert "section_number = $1" in pool.calls[0][0]
    assert "full_text ILIKE" in pool.calls[1][0] and pool.calls[1][1][0] == "199.18"
    # a part citation has no fallback: an empty part stays empty
    pool = _CapturePool(rows=[], text_rows=[hit])
    assert asyncio.run(R._identifier_search(R._extract_identifiers("46 CFR 34"), pool)) == []
    assert len(pool.calls) == 1


def _row(i, sim, sec, source="solas"):
    return {"id": i, "source": source, "section_number": sec, "section_title": "",
            "full_text": f"text {i}", "similarity": sim}


class _RetrievePool:
    """Identifier lookups get Reg.20's five chunks; everything else, nothing."""

    def __init__(self):
        self.reg20 = [_row(f"r{n}", 0.0, "SOLAS Ch.III Reg.20") for n in range(1, 6)]

    async def fetch(self, sql, *args):
        if "section_number = $1" in sql:
            return [dict(r) for r in self.reg20]
        return []

    async def fetchval(self, *a, **k):
        return 0


def test_cited_section_keeps_all_its_chunks(monkeypatch):
    monkeypatch.setattr(R, "SOURCE_GROUPS", {"imo": ("solas",), "cfr": ("cfr_46",)})
    stats = {"solas": (1700, frozenset({"intl"})), "cfr_46": (30000, frozenset({"us"}))}

    async def embed(key, query):
        return "[0.1]"

    async def available(pool):
        return set(stats)

    async def source_stats(pool):
        return stats

    async def fake_group(pool, vec, sources, k, juris):
        if sources == ["solas"]:        # vector search already found 2 of Reg.20's chunks
            return [_row("r1", 0.50, "SOLAS Ch.III Reg.20"), _row("r2", 0.48, "SOLAS Ch.III Reg.20"),
                    _row("u1", 0.60, "SOLAS Ch.III Reg.19")]
        return [_row("c1", 0.62, "46 CFR 199.180", source="cfr_46")]

    monkeypatch.setattr(R, "_embed_query", embed)
    monkeypatch.setattr(R, "_get_available_sources", available)
    monkeypatch.setattr(R, "_get_source_stats", source_stats)
    monkeypatch.setattr(R, "_fetch_group", fake_group)
    profile = {"vessel_type": "Containership", "flag_state": "United States"}
    out = asyncio.run(R.retrieve("SOLAS III/20 lifeboat lowering", _RetrievePool(), "key",
                                 vessel_profile=profile, limit=30))
    reg20 = {c["id"]: c["similarity"] for c in out if c["section_number"] == "SOLAS Ch.III Reg.20"}
    assert set(reg20) == {"r1", "r2", "r3", "r4", "r5"}          # cap 5 for a cited section
    assert all(abs(s - (0.62 + 0.05)) < 1e-9 for s in reg20.values())   # found ones boosted too

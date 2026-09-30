"""2026-09-30 — a chip whose guessed source lacks the section opens it from
a sibling source (CG-CVC PL 15-03 is stored with the NMC letters)."""
import asyncio

import pytest
from fastapi import HTTPException

from app.routers import regulations as R


class _Conn:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    async def fetch(self, sql, *args):
        self.queries.append(args)
        if "WHERE source = $1 AND section_number = $2" in sql:
            return self.rows.get(args, [])
        return []


class _Pool:
    def __init__(self, rows):
        self.conn = _Conn(rows)

    def acquire(self):
        pool = self

        class _Ctx:
            async def __aenter__(self):
                return pool.conn

            async def __aexit__(self, *exc):
                return False

        return _Ctx()


ROW = {"section_title": "Crediting recent service", "full_text": "Policy text.",
       "effective_date": None, "up_to_date_as_of": None}


def test_sibling_source_resolves_the_exact_section(monkeypatch):
    async def no_refs(pool, sn):
        return []

    monkeypatch.setattr(R, "_find_references", no_refs)
    pool = _Pool({("nmc_policy", "CG-CVC PL 15-03"): [ROW]})
    detail = asyncio.run(R._load_regulation(pool, "uscg_cvc", "CG-CVC PL 15-03"))
    assert detail.source == "nmc_policy" and detail.full_text == "Policy text."
    assert pool.conn.queries[:2] == [("uscg_cvc", "CG-CVC PL 15-03"), ("nmc_policy", "CG-CVC PL 15-03")]


def test_sources_without_siblings_still_404(monkeypatch):
    async def no_refs(pool, sn):
        return []

    monkeypatch.setattr(R, "_find_references", no_refs)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(R._load_regulation(_Pool({}), "cfr_46", "46 CFR 999.1"))
    assert exc.value.status_code == 404

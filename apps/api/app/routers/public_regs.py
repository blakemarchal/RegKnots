"""Public regulation pages (growth plan step 3, 2026-10-14).

Read-only, no sign-in: the published rows of seo_pages (app/seo_pages.py) for
the web's /regs pages, hub pages and sitemap. Only published pages are
returned, and only from the U.S. government sources the selection uses.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import seo_pages
from app.db import get_pool

router = APIRouter(prefix="/public/regs", tags=["public"])


class CollectionOut(BaseModel):
    slug: str
    title: str
    blurb: str
    pages: int


class PageSummary(BaseModel):
    slug: str
    title: str
    display_number: str
    collection: str
    meta_description: str | None
    updated_at: datetime


class RelatedLink(BaseModel):
    section_number: str
    slug: str | None = None        # our page, when it is published
    url: str | None = None         # otherwise eCFR, for a CFR section


class PageOut(BaseModel):
    slug: str
    title: str
    display_number: str
    section_number: str
    section_title: str | None
    collection: str
    collection_title: str
    meta_description: str | None
    content: dict[str, Any]
    source_text: str
    source_label: str
    source_url: str | None
    up_to_date_as_of: date | None
    updated_at: datetime
    related: list[RelatedLink]
    previous: PageSummary | None = None
    next: PageSummary | None = None


def _natural_key(section_number: str) -> list[tuple]:
    """"46 CFR 10.9" before "46 CFR 10.10". Each part is (0, int) or (1, str),
    so keys from different sources still compare (2026-10-14: the all-pages
    list mixed COLREGs and CFR keys and raised TypeError)."""
    return [(0, int(t)) if t.isdigit() else (1, t) for t in re.split(r"(\d+)", section_number)]


def _sort_key(row) -> list[tuple]:
    """Natural order; COLREGs Rules before Annexes, Annexes by Roman numeral."""
    roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}
    number = row["section_number"]
    m = re.match(r"^COLREGS (Rule|Annex) (\w+)$", number)
    if m:
        n = int(m.group(2)) if m.group(2).isdigit() else roman.get(m.group(2), 99)
        return [(1, "COLREGS"), (0, 0 if m.group(1) == "Rule" else 1), (0, n)]
    return _natural_key(number)


def _source_label(source: str, section_number: str, as_of: date | None) -> str:
    if source.startswith("cfr_"):
        when = f", current as of {as_of:%B} {as_of.day}, {as_of.year}" if as_of else ""
        return f"Electronic Code of Federal Regulations (eCFR){when}"
    if source == "colregs":
        return "U.S. Coast Guard, Navigation Rules and Regulations Handbook"
    if source == "nvic":
        return f"U.S. Coast Guard, {section_number} (main body; enclosures not shown)"
    return "U.S. Coast Guard"


def _summary(row) -> PageSummary:
    return PageSummary(slug=row["slug"], title=row["title"], display_number=row["display_number"],
                       collection=row["collection"], meta_description=row["meta_description"],
                       updated_at=row["updated_at"])


_SUMMARY_COLS = "slug, title, display_number, collection, meta_description, updated_at, section_number"


@router.get("/collections", response_model=list[CollectionOut])
async def collections(pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> list[CollectionOut]:
    counts = {r["collection"]: r["n"] for r in await pool.fetch(
        "SELECT collection, count(*) AS n FROM seo_pages WHERE status = 'published' GROUP BY 1")}
    return [CollectionOut(slug=c.slug, title=c.title, blurb=c.blurb, pages=counts.get(c.slug, 0))
            for c in seo_pages.COLLECTIONS if counts.get(c.slug)]


@router.get("", response_model=list[PageSummary])
async def list_pages(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    collection: str | None = Query(default=None, max_length=40),
) -> list[PageSummary]:
    if collection is not None and collection not in seo_pages.COLLECTION_BY_SLUG:
        raise HTTPException(status_code=404, detail="No such collection")
    rows = await pool.fetch(
        f"SELECT {_SUMMARY_COLS} FROM seo_pages WHERE status = 'published'"
        + (" AND collection = $1" if collection else ""),
        *([collection] if collection else []),
    )
    return [_summary(r) for r in sorted(rows, key=_sort_key)]


@router.get("/links", response_model=list[RelatedLink])
async def links(
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    s: list[str] = Query(default=[]),
) -> list[RelatedLink]:
    """2026-10-16 — where each cited section can be read without an account, for
    the chips in the free answer (web GuestAsk): our page when it is published,
    else eCFR for a CFR section, else neither. Answers in the order asked."""
    wanted = [x.strip() for x in s if x and x.strip() and len(x) <= 80][:20]
    corpus_form = [re.sub(r"^COLREGs\b", "COLREGS", x) for x in wanted]
    ours = {r["section_number"]: r["slug"] for r in await pool.fetch(
        "SELECT section_number, slug FROM seo_pages WHERE status = 'published' AND section_number = ANY($1::text[])",
        corpus_form)} if corpus_form else {}
    return [RelatedLink(section_number=asked, slug=ours.get(c), url=None if c in ours else seo_pages.ecfr_url(c))
            for asked, c in zip(wanted, corpus_form)]


@router.get("/page/{slug}", response_model=PageOut)
async def get_page(slug: str, pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> PageOut:
    if not re.fullmatch(r"[a-z0-9-]{1,80}", slug):
        raise HTTPException(status_code=404, detail="Page not found")
    row = await pool.fetchrow(
        """SELECT slug, title, display_number, section_number, section_title, collection, source,
                  meta_description, content, source_text, up_to_date_as_of, updated_at
           FROM seo_pages WHERE slug = $1 AND status = 'published'""",
        slug,
    )
    if row is None or row["source"] not in seo_pages.PUBLIC_SOURCES:
        raise HTTPException(status_code=404, detail="Page not found")
    content = row["content"]
    content = json.loads(content) if isinstance(content, str) else (content or {})

    # Related sections: our page when published, else eCFR for a CFR section.
    wanted = [s for s in content.get("related_sections", []) if s and s != row["section_number"]][:12]
    corpus_form = [re.sub(r"^COLREGs\b", "COLREGS", s.strip()) for s in wanted]
    ours = {r["section_number"]: r["slug"] for r in await pool.fetch(
        "SELECT section_number, slug FROM seo_pages WHERE status = 'published' AND section_number = ANY($1::text[])",
        corpus_form)}
    related = [RelatedLink(section_number=seo_pages.display_number(s), slug=ours.get(s), url=None if s in ours
                           else seo_pages.ecfr_url(s)) for s in corpus_form]

    # Neighbours in the same collection, for previous / next links.
    siblings = sorted(await pool.fetch(
        f"SELECT {_SUMMARY_COLS} FROM seo_pages WHERE status = 'published' AND collection = $1",
        row["collection"]), key=_sort_key)
    idx = next((i for i, s in enumerate(siblings) if s["slug"] == slug), None)
    previous = _summary(siblings[idx - 1]) if idx else None
    nxt = _summary(siblings[idx + 1]) if idx is not None and idx + 1 < len(siblings) else None

    return PageOut(
        slug=row["slug"], title=row["title"], display_number=row["display_number"],
        section_number=row["section_number"], section_title=row["section_title"],
        collection=row["collection"], collection_title=seo_pages.COLLECTION_BY_SLUG[row["collection"]].title,
        meta_description=row["meta_description"], content=content, source_text=row["source_text"],
        source_label=_source_label(row["source"], row["display_number"], row["up_to_date_as_of"]),
        source_url=seo_pages.ecfr_url(row["section_number"]), up_to_date_as_of=row["up_to_date_as_of"],
        updated_at=row["updated_at"], related=related, previous=previous, next=nxt,
    )

"""Corpus gaps (2026-10-08, answer pipeline phase 2).

What the coverage check found missing from the library, whether the web
research found it, and what the ingest task did with it. The working list
that replaces hedge audits: a found-but-skipped item is a candidate source to
add by hand; an ingested document can be removed if it shouldn't be there.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.routers.admin import audit_log, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class CorpusGap(BaseModel):
    id: str
    created_at: datetime
    user_email: str | None
    question: str
    item: str
    search_query: str | None
    coverage: str | None
    web_searched: bool
    found: bool
    answer: str | None
    sources: list[dict]
    status: str
    ingest_note: str | None
    ingested_section: str | None
    ingest_url: str | None
    latency_ms: int | None


class GapSummary(BaseModel):
    gaps: list[CorpusGap]
    counts: dict[str, int]
    web_ingest_documents: int


@router.get("/corpus-gaps", response_model=GapSummary)
async def list_gaps(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    status_filter: str | None = Query(None, alias="status"),
    exclude_internal: bool = Query(True),
    limit: int = Query(200, ge=1, le=500),
) -> GapSummary:
    uf = " AND u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE" if exclude_internal else ""
    sf = " AND g.status = $2" if status_filter else ""
    args: list = [limit] + ([status_filter] if status_filter else [])
    rows = await pool.fetch(
        f"""
        SELECT g.*, u.email AS user_email
        FROM corpus_gaps g LEFT JOIN users u ON u.id = g.user_id
        WHERE true{uf}{sf}
        ORDER BY g.created_at DESC
        LIMIT $1
        """,
        *args,
    )
    counts = {r["status"]: r["n"] for r in await pool.fetch(
        "SELECT status, count(*) AS n FROM corpus_gaps GROUP BY 1")}
    docs = await pool.fetchval(
        "SELECT count(DISTINCT section_number) FROM regulations WHERE source = 'web_ingest'")
    gaps = []
    for r in rows:
        src = r["sources"]
        if isinstance(src, str):
            src = json.loads(src or "[]")
        gaps.append(CorpusGap(
            id=str(r["id"]), created_at=r["created_at"], user_email=r["user_email"], question=r["question"],
            item=r["item"], search_query=r["search_query"], coverage=r["coverage"], web_searched=r["web_searched"],
            found=r["found"], answer=r["answer"], sources=src or [], status=r["status"],
            ingest_note=r["ingest_note"], ingested_section=r["ingested_section"], ingest_url=r["ingest_url"],
            latency_ms=r["latency_ms"],
        ))
    return GapSummary(gaps=gaps, counts=counts, web_ingest_documents=int(docs or 0))


@router.post("/corpus-gaps/{gap_id}/dismiss")
async def dismiss_gap(
    gap_id: uuid.UUID,
    admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict:
    done = await pool.fetchval(
        "UPDATE corpus_gaps SET status = 'dismissed', updated_at = now() WHERE id = $1 RETURNING id", gap_id)
    if not done:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Gap not found")
    await audit_log(pool, admin, "dismiss_corpus_gap", str(gap_id))
    return {"ok": True}


@router.delete("/web-ingest")
async def remove_web_document(
    admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    section: str = Query(..., max_length=300),
) -> dict:
    """Remove a document the ingest task added (every chunk of the section)."""
    result = await pool.execute(
        "DELETE FROM regulations WHERE source = 'web_ingest' AND section_number = $1", section)
    removed = int(result.split()[-1]) if result else 0
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    await pool.execute(
        "UPDATE corpus_gaps SET status = 'dismissed', ingest_note = 'removed by an admin', updated_at = now() "
        "WHERE ingested_section = $1", section)
    await audit_log(pool, admin, "remove_web_ingest_document", None, {"section": section, "chunks": removed})
    return {"removed": removed}

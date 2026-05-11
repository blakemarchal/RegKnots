"""
GET /regulations/{source}/{section_number} — fetch full text for a regulation section.

section_number is URL-encoded by the client (e.g. "133.45" → "133.45", "164.01-5" → "164.01-5").
If a section has multiple chunks they are concatenated in chunk_index order.

Sprint D6.88 Phase 1 — Option B copyright posture. The full text from
the corpus is returned for ALL sources, including the IMO instruments
(SOLAS, STCW, COLREGS) that previously had their text replaced by a
placeholder pointing users to imo.org. Mariners overwhelmingly access
this content through their company SMS / class society / flag state;
our job is to help paying users verify their compliance citations,
not to be a content-protection layer for IMO Publishing's commercial
editions. The `copyrighted` flag on the response is retained as
informational metadata so the viewer can render the attribution
badge — it no longer blocks content delivery.

Every lookup writes one row to `citation_lookups` (fire-and-forget)
so we have access-pattern telemetry to (a) drive Phase 2 corpus
prioritization and (b) substantiate the "compliance tool, not
content service" posture if IMO Publishing ever reaches out.
"""

import asyncio
import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/regulations", tags=["regulations"])


# Informational only. Frontend uses this flag to render the small
# attribution badge ("IMO Copyrighted Content — official text:
# imo.org") around IMO instrument content. NOT a content gate.
# Add a source here when you ingest a new IMO instrument that
# carries the same copyright + attribution requirement.
_IMO_COPYRIGHTED_SOURCES = {
    "solas", "solas_supplement",
    "stcw", "stcw_supplement",
    "colregs",
    "ism", "ism_supplement",
    "imdg",
    "imo_hsc", "imo_igc", "imo_ibc",
}


class RegulationDetail(BaseModel):
    source: str
    section_number: str
    section_title: str | None
    full_text: str
    effective_date: str | None
    up_to_date_as_of: str | None
    copyrighted: bool = False


async def _load_regulation(pool, source: str, section_number: str) -> RegulationDetail:
    """Shared loader used by both the path-based and query-based endpoints.

    Returns the actual full_text from the regulations table for every
    source. The IMO copyright filter that previously replaced the text
    with a placeholder was removed in D6.88 Phase 1 — see module
    docstring for rationale.
    """
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT section_title, full_text, effective_date, up_to_date_as_of
            FROM regulations
            WHERE source = $1 AND section_number = $2
            ORDER BY chunk_index
            """,
            source,
            section_number,
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Regulation {source}/{section_number} not found",
        )

    section_title = rows[0]["section_title"]
    effective_date = rows[0]["effective_date"]
    up_to_date_as_of = rows[0]["up_to_date_as_of"]
    full_text = "\n\n".join(r["full_text"] for r in rows if r["full_text"])

    return RegulationDetail(
        source=source,
        section_number=section_number,
        section_title=section_title,
        full_text=full_text,
        effective_date=str(effective_date) if effective_date else None,
        up_to_date_as_of=str(up_to_date_as_of) if up_to_date_as_of else None,
        copyrighted=source in _IMO_COPYRIGHTED_SOURCES,
    )


async def _log_citation_lookup(
    pool,
    *,
    user_id: uuid.UUID | None,
    source: str,
    section_number: str,
    found: bool,
) -> None:
    """Persist a citation-lookup event for telemetry.

    Fire-and-forget from the request path: never block the user's
    response on a telemetry write. Failures swallow silently — the
    table is observational, not transactional.
    """
    try:
        await pool.execute(
            """
            INSERT INTO citation_lookups (user_id, source, section_number, found)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            source[:64],
            section_number[:500],
            found,
        )
    except Exception as exc:
        # Don't surface — the user already got their answer.
        logger.debug(
            "citation_lookups insert failed (non-fatal): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )


def _schedule_lookup_log(
    pool,
    *,
    user_id_str: str,
    source: str,
    section_number: str,
    found: bool,
) -> None:
    """Schedule the citation-lookup log as a background task on the
    event loop. The lookup response goes back to the client without
    waiting for the telemetry write to land."""
    try:
        user_uuid = uuid.UUID(user_id_str) if user_id_str else None
    except (ValueError, TypeError):
        user_uuid = None
    asyncio.create_task(
        _log_citation_lookup(
            pool,
            user_id=user_uuid,
            source=source,
            section_number=section_number,
            found=found,
        )
    )


@router.get("/lookup", response_model=RegulationDetail)
async def lookup_regulation(
    source: Annotated[str, Query(description="Regulation source, e.g. stcw")],
    section_number: Annotated[str, Query(description="Section number, e.g. 'STCW Ch.II Reg.II/2'")],
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> RegulationDetail:
    """Look up a regulation by (source, section_number) via query parameters.

    Query params avoid the path-segment issue where section_numbers containing
    forward slashes (e.g. ``STCW Ch.II Reg.II/2``) get decoded by the reverse
    proxy and split into an extra path segment, causing a 404.
    """
    try:
        detail = await _load_regulation(pool, source, section_number)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            _schedule_lookup_log(
                pool, user_id_str=user.user_id,
                source=source, section_number=section_number, found=False,
            )
        raise

    _schedule_lookup_log(
        pool, user_id_str=user.user_id,
        source=source, section_number=section_number, found=True,
    )
    return detail


@router.get("/{source}/{section_number}", response_model=RegulationDetail)
async def get_regulation(
    source: Annotated[str, Path(description="Regulation source, e.g. cfr_46")],
    section_number: Annotated[str, Path(description="CFR section number, e.g. 133.45")],
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> RegulationDetail:
    try:
        detail = await _load_regulation(pool, source, section_number)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            _schedule_lookup_log(
                pool, user_id_str=user.user_id,
                source=source, section_number=section_number, found=False,
            )
        raise

    _schedule_lookup_log(
        pool, user_id_str=user.user_id,
        source=source, section_number=section_number, found=True,
    )
    return detail

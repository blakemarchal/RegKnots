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
import re
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)


# Sprint D6.88 Phase 2 — paragraph-suffix fallback. The model commonly
# cites granular sub-references the corpus is not ingested at:
#   "SOLAS Ch.VI Reg.2, para. 5"   — actual row: "SOLAS Ch.VI Reg.2"
#   "33 CFR 151.25(d)"             — actual row: "33 CFR 151.25"
#   "MARPOL Annex I Reg.20.1"      — actual row: "MARPOL Annex I Reg.20"
# When the exact section_number 404s, we strip these suffixes and
# retry against the parent. Result: the chip click lands on the
# parent regulation, which contains the cited sub-reference in its
# body text. UX: header shows the citation as the model wrote it
# (with the para/sub suffix), body shows the parent text. Acceptable
# tradeoff vs. always 404'ing.
#
# Patterns are applied in order, each stripping ONE suffix layer.
_LOOKUP_SUFFIX_PATTERNS = [
    # ", para. 5"  /  ", para.5"  /  ", paragraph 5"  /  ", para. 5.2"
    re.compile(r",\s*para(?:graph)?\.?\s*\d+(?:\.\d+)*\s*$", re.IGNORECASE),
    # Trailing parenthesized sub: "(a)", "(b)(2)", "(1)" — CFR style
    re.compile(r"\s*\([a-z0-9]+\)(?:\([a-z0-9]+\))*\s*$", re.IGNORECASE),
    # Trailing ".N.N" sub-numbering, e.g. "Reg.20.1.3" → "Reg.20"
    re.compile(r"(?<=\d)\.\d+(?:\.\d+)+\s*$"),
    # Trailing " Part II" / " Part III" sub-section (common on MARPOL
    # appendix references — "Appendix III Part II" → "Appendix III").
    re.compile(r"\s+Part\s+[IVX]+\s*$"),
]


def _strip_lookup_suffix(section_number: str) -> str | None:
    """Try each suffix pattern; return the cleaned section_number if
    any one stripped a suffix, else None. Lets us distinguish "we
    fell back to parent" from "no fallback applicable.\""""
    for pat in _LOOKUP_SUFFIX_PATTERNS:
        stripped = pat.sub("", section_number).strip()
        if stripped and stripped != section_number:
            return stripped
    return None


# Sprint D6.88 Phase 3 — full-word ↔ abbreviated normalizations for
# DB lookup. The model commonly writes full-word forms ("MARPOL Annex
# VI Appendix VII", "MARPOL Annex I Regulation 20.1") while the
# corpus stores DB-canonical abbreviations ("App.VII", "Reg.20.1").
# These substitutions are applied as a SECOND fallback when the
# initial lookup and suffix-strip both miss — so DB rows with the
# canonical form get matched without requiring the user / chip to
# know the abbreviation convention.
#
# Substitutions are applied left-to-right, all-at-once; the order
# doesn't matter because the patterns don't overlap. Each pattern
# consumes the trailing whitespace as well so the result is the
# DB-canonical no-space-after-abbreviation form ("App.VII" not
# "App. VII", which is how MARPOL rows are actually stored).
_NORMALIZATION_PATTERNS = [
    # "Appendix " → "App."  (collapse space between abbrev and identifier)
    (re.compile(r"\bAppendix\b\.?\s*", re.IGNORECASE), "App."),
    # "Chapter " → "Ch."
    (re.compile(r"\bChapter\b\.?\s*", re.IGNORECASE), "Ch."),
    # "Regulation " → "Reg." (word boundary protects "Regulations"/"Regulator")
    (re.compile(r"\bRegulation\b\.?\s*", re.IGNORECASE), "Reg."),
    # Collapse double-space artifacts.
    (re.compile(r"\s{2,}"), " "),
]


def _normalize_for_lookup(section_number: str) -> str | None:
    """Convert full-word forms to DB-canonical abbreviations. Returns
    the normalized string if it differs from the input, else None.
    Used as a fallback when the initial exact-match and the
    suffix-strip both miss."""
    normalized = section_number
    for pat, repl in _NORMALIZATION_PATTERNS:
        normalized = pat.sub(repl, normalized)
    normalized = normalized.strip()
    if normalized and normalized != section_number:
        return normalized
    return None

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

    Sprint D6.88 Phase 2 — paragraph-suffix fallback. If the exact
    section_number 404s and the citation has a known sub-reference
    suffix ("..., para. 5", "(a)", ".1.3"), strip it and look up the
    parent. The body text contains the cited sub-reference; the
    header preserves what the model wrote. Without this fallback,
    every paragraph-level chip click would 404 because the corpus
    is ingested at regulation level, not paragraph level.
    """
    async def _fetch(sn: str):
        async with pool.acquire() as conn:
            return await conn.fetch(
                """
                SELECT section_title, full_text, effective_date, up_to_date_as_of
                FROM regulations
                WHERE source = $1 AND section_number = $2
                ORDER BY chunk_index
                """,
                source,
                sn,
            )

    rows = await _fetch(section_number)
    resolved_sn = section_number

    # Phase 2 fallback: strip granular suffix(es) and retry once.
    # Apply up to two strip passes (e.g., "Reg.2, para.5.1" → "Reg.2,
    # para.5" → "Reg.2") so multi-layer suffixes still land somewhere.
    if not rows:
        candidate = section_number
        for _ in range(2):
            stripped = _strip_lookup_suffix(candidate)
            if not stripped:
                break
            candidate = stripped
            rows = await _fetch(candidate)
            if rows:
                resolved_sn = candidate
                logger.info(
                    "regulations lookup fallback (suffix): %s/%s -> %s/%s",
                    source, section_number, source, candidate,
                )
                break

    # Phase 3 fallback: full-word → DB-canonical abbreviation
    # ("Appendix" → "App.", "Chapter" → "Ch.", "Regulation" → "Reg.").
    # The model writes the full-word form in answers; the corpus
    # stores the abbreviated form. Try the normalized lookup, and if
    # that misses too, ALSO try the normalized form with suffixes
    # stripped (handles "Appendix III Part II" → "App.III").
    if not rows:
        candidate = section_number
        normalized = _normalize_for_lookup(candidate)
        if normalized:
            rows = await _fetch(normalized)
            if rows:
                resolved_sn = normalized
                logger.info(
                    "regulations lookup fallback (normalize): %s/%s -> %s/%s",
                    source, section_number, source, normalized,
                )
            else:
                # Normalize + strip combined
                stripped = _strip_lookup_suffix(normalized)
                if stripped:
                    rows = await _fetch(stripped)
                    if rows:
                        resolved_sn = stripped
                        logger.info(
                            "regulations lookup fallback (normalize+strip): "
                            "%s/%s -> %s/%s",
                            source, section_number, source, stripped,
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

    # Phase 2 — if we resolved via fallback, prefix a small italic note
    # so the user knows the body is the parent regulation and they
    # need to scan for the specific paragraph the citation referenced.
    # Use ascii-only chars for safe rendering in copy-paste contexts.
    if resolved_sn != section_number:
        # Extract the granular reference for the note (e.g., "paragraph 5")
        note = (
            f"_Note: showing parent regulation **{resolved_sn}**. "
            f"The citation **{section_number}** references a specific "
            f"paragraph or sub-paragraph within this regulation — scan "
            f"the text below to find it._\n\n---\n\n"
        )
        full_text = note + full_text

    return RegulationDetail(
        source=source,
        section_number=section_number,  # preserve what the chip said
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

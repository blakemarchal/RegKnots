"""
pgvector semantic search with source-diversified fetch and soft re-ranking.

Retrieval strategy:

1. Embed the query once.
2. Run one vector search per configured source group, CONCURRENTLY. Each
   group gets its own top-N candidate pool, so small sources (COLREGs: 102,
   SOLAS: 742) aren't outranked by large ones (CFR: ~33K chunks) just
   because the large sources have more chunks to draw from.
3. Merge and deduplicate by chunk id.
4. Apply two soft boosts:
     - Source affinity: when the query unambiguously targets a source
       (e.g., mentions COLREGs, 46 CFR, SOLAS chapter, STCW), boost chunks
       from that source's group.
     - Vessel profile: when a vessel_profile is provided, boost chunks
       whose full_text mentions the vessel's type / route / cargo.
5. Sort by similarity + boosts, return top `limit`.

Adding a new source (e.g., MARPOL) is just a one-line edit to SOURCE_GROUPS
and an entry in _source_affinity if it has distinctive keywords. No other
code changes required — the diversified fetch adapts automatically.
"""

import asyncio
import logging
import re
import time

import asyncpg
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"

# ── Source groups ────────────────────────────────────────────────────────────
#
# Sources are grouped by regulatory body/type so related sub-sources stay
# together. Each group fetches its own top-N independently in Phase 1.
SOURCE_GROUPS: dict[str, tuple[str, ...]] = {
    "cfr": ("cfr_33", "cfr_46", "cfr_49"),
    "colregs": ("colregs",),
    "solas": ("solas", "solas_supplement"),
    "nvic": ("nvic",),
    "stcw": ("stcw", "stcw_supplement"),
    "ism": ("ism",),
    "erg": ("erg",),
}

# Per-group candidate pool sizes. CFR is larger because it covers three
# sub-titles (~33K total chunks) and needs room for intra-CFR diversity.
_CANDIDATES_PER_GROUP: dict[str, int] = {
    "cfr": 12,
    "erg": 8,  # ERG needs more candidates: its lookup-table + response-card
               # structure means Table chunks can crowd out Orange Guides at top-6.
}
_DEFAULT_CANDIDATES_PER_GROUP = 6

# Reverse index: source_code → group_name. Built once at module load.
_SOURCE_TO_GROUP: dict[str, str] = {
    src: group_name
    for group_name, srcs in SOURCE_GROUPS.items()
    for src in srcs
}

# ── Source-existence cache ───────────────────────────────────────────────────
#
# Populated lazily on the first retrieve() call with a single
# `SELECT DISTINCT source` query, then reused for the life of the process.
# This lets us skip groups whose sources haven't been ingested yet (e.g.,
# MARPOL before it exists) without a per-call overhead.
_AVAILABLE_SOURCES: set[str] | None = None
_AVAILABLE_SOURCES_LOCK = asyncio.Lock()


async def _get_available_sources(pool: asyncpg.Pool) -> set[str]:
    global _AVAILABLE_SOURCES
    if _AVAILABLE_SOURCES is not None:
        return _AVAILABLE_SOURCES
    async with _AVAILABLE_SOURCES_LOCK:
        if _AVAILABLE_SOURCES is not None:
            return _AVAILABLE_SOURCES
        rows = await pool.fetch(
            "SELECT DISTINCT source FROM regulations WHERE embedding IS NOT NULL"
        )
        _AVAILABLE_SOURCES = {r["source"] for r in rows}
        logger.info(
            "Retriever source cache populated: %s",
            sorted(_AVAILABLE_SOURCES),
        )
    return _AVAILABLE_SOURCES


# ── Source affinity (query-keyword → group boost) ────────────────────────────
#
# A soft nudge, NOT a filter. The diversified fetch already guarantees each
# group has candidates in the pool; these boosts just promote the clearly-
# targeted group within the final top-8.

_COLREGS_TERMS: tuple[str, ...] = (
    "colreg", "collision regulation", "rules of the road", "rule of the road",
    "72 colregs",
    "head-on", "head on situation", "crossing situation", "overtaking",
    "give-way", "give way vessel", "stand-on", "stand on vessel",
    "look-out", "lookout", "risk of collision", "narrow channel",
    "traffic separation", "restricted visibility",
    "navigation light", "navigation lights", "masthead light",
    "sidelight", "side light", "stern light", "anchor light",
    "fog signal", "sound signal", "whistle signal",
    "manoeuvring signal", "maneuvering signal",
    "shapes",
)
_COLREGS_RULE_RE = re.compile(r"\brules?\s*([0-9]{1,2})\b", re.IGNORECASE)
_COLREGS_ANNEX_RE = re.compile(r"\bannex\s*([ivx]+|[0-9])\b", re.IGNORECASE)

_SOLAS_TERMS: tuple[str, ...] = (
    "solas", "safety of life at sea", "msc.",
    "regulation ii", "regulation iii", "regulation iv", "regulation v",
    "chapter ii", "chapter iii", "chapter iv", "chapter v",
)

_STCW_TERMS: tuple[str, ...] = (
    "stcw", "training certification watchkeeping", "seafarer credential",
    "endorsement", "certificate of competency", "watchkeeping",
)

_NVIC_TERMS: tuple[str, ...] = (
    "nvic", "navigation vessel inspection circular",
    "uscg policy", "coast guard guidance", "coast guard policy",
)

# ISM Code keywords. Unambiguous full-phrase terms go in the tuple. The
# abbreviation regex uses word boundaries so "ism" doesn't match "prism" or
# "tourism", and "dpa"/"smc"/"doc 88" only match as standalone tokens.
_ISM_TERMS: tuple[str, ...] = (
    "ism code", "international safety management",
    "safety management system",
    "designated person ashore", "designated person",
    "document of compliance",
    "safety management certificate",
)
_ISM_ABBR_RE = re.compile(
    r"\b(?:ism|dpa|smc|doc\s*88)\b",
    re.IGNORECASE,
)

_ERG_TERMS: tuple[str, ...] = (
    # NOTE: "erg" is matched via _ERG_ABBR_RE with word boundaries — do NOT
    # put it here, because "erg" is a substring of "emergency" and would
    # false-positive on every query containing that word.
    "emergency response guidebook", "emergency response guide",
    "emergency response for", "emergency response to",
    "hazmat", "hazardous material", "dangerous goods",
    "un number", "na number", "placard",
    "isolation distance", "protective action",
    "spill", "chemical spill", "toxic inhalation",
    "guide number", "guide 1",
)
_ERG_ABBR_RE = re.compile(r"\berg\b", re.IGNORECASE)
_ERG_GUIDE_RE = re.compile(r"\bguide\s*(\d{3})\b", re.IGNORECASE)
_ERG_UN_RE = re.compile(r"\b(?:UN|NA)\s*\d{4}\b", re.IGNORECASE)


def _source_affinity(query: str) -> dict[str, float]:
    """Return a boost value per source group based on query keywords.

    The diversified fetch guarantees each group has candidates — this
    function just nudges ranking when the query clearly targets a source.
    """
    q = query.lower()
    boosts: dict[str, float] = {}

    if (
        any(t in q for t in _COLREGS_TERMS)
        or _COLREGS_RULE_RE.search(q)
        or _COLREGS_ANNEX_RE.search(q)
    ):
        boosts["colregs"] = 0.20

    if any(t in q for t in _SOLAS_TERMS):
        boosts["solas"] = 0.20

    if any(t in q for t in _STCW_TERMS):
        boosts["stcw"] = 0.20

    if any(t in q for t in _NVIC_TERMS):
        boosts["nvic"] = 0.20

    if any(t in q for t in _ISM_TERMS) or _ISM_ABBR_RE.search(q):
        boosts["ism"] = 0.20

    if (
        any(t in q for t in _ERG_TERMS)
        or _ERG_ABBR_RE.search(q)
        or _ERG_GUIDE_RE.search(q)
        or _ERG_UN_RE.search(q)
    ):
        boosts["erg"] = 0.20

    if "cfr" in q or "code of federal" in q:
        boosts["cfr"] = 0.15
        if any(
            t in q
            for t in ("33 cfr", "title 33", "46 cfr", "title 46", "49 cfr", "title 49")
        ):
            boosts["cfr"] = 0.25

    return boosts


# ── Query embedding ──────────────────────────────────────────────────────────


async def _embed_query(openai_api_key: str, query: str) -> str:
    oai = AsyncOpenAI(api_key=openai_api_key)
    try:
        resp = await oai.embeddings.create(model=_EMBED_MODEL, input=[query])
    finally:
        await oai.close()
    embedding = resp.data[0].embedding
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


# ── Per-group SQL fetch ──────────────────────────────────────────────────────


async def _fetch_group(
    pool: asyncpg.Pool,
    vec_literal: str,
    group_sources: list[str],
    candidates: int,
) -> list[dict]:
    rows = await pool.fetch(
        """
        SELECT id, source, section_number, section_title, full_text,
               1 - (embedding <=> $1::vector) AS similarity
        FROM regulations
        WHERE embedding IS NOT NULL
          AND source = ANY($3)
        ORDER BY embedding <=> $1::vector
        LIMIT $2
        """,
        vec_literal,
        candidates,
        group_sources,
    )
    return [dict(r) for r in rows]


# ── Public API ───────────────────────────────────────────────────────────────


async def retrieve(
    query: str,
    pool: asyncpg.Pool,
    openai_api_key: str,
    vessel_profile: dict | None = None,
    limit: int = 8,
    sources: list[str] | None = None,
) -> list[dict]:
    """Return semantically relevant regulation chunks.

    Args:
        query:          The user's question.
        pool:           asyncpg connection pool.
        openai_api_key: Key for OpenAI embeddings API.
        vessel_profile: Optional vessel profile dict for soft re-ranking.
        limit:          Max chunks to return (default 8).
        sources:        Explicit source filter (e.g. ['cfr_46']). When given,
                        the diversified fetch is skipped and a single
                        filtered query is run — preserves the citation-
                        lookup code path.

    Returns:
        List of dicts: id, source, section_number, section_title, full_text,
        similarity, plus an internal `_score` added by _rerank.
    """
    t0 = time.perf_counter()

    vec_literal = await _embed_query(openai_api_key, query)

    if sources:
        # Explicit source filter — single query, no diversification.
        fetch_limit = max(limit * 3, 20)
        rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM regulations
            WHERE embedding IS NOT NULL
              AND source = ANY($3)
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_literal,
            fetch_limit,
            sources,
        )
        # Deduplicate by section_number (keep highest similarity)
        candidates = []
        seen_sections: dict[str, int] = {}
        for r in rows:
            chunk = dict(r)
            sec = chunk.get("section_number", "")
            if sec and sec in seen_sections:
                existing_idx = seen_sections[sec]
                if chunk["similarity"] > candidates[existing_idx]["similarity"]:
                    candidates[existing_idx] = chunk
                continue
            if sec:
                seen_sections[sec] = len(candidates)
            candidates.append(chunk)
        active_groups: list[str] = []
    else:
        # Diversified fetch: one query per source group that has data, all
        # running concurrently on the HNSW index.
        available = await _get_available_sources(pool)
        tasks: list = []
        active_groups = []
        for group_name, group_sources in SOURCE_GROUPS.items():
            present = [s for s in group_sources if s in available]
            if not present:
                continue
            n = _CANDIDATES_PER_GROUP.get(group_name, _DEFAULT_CANDIDATES_PER_GROUP)
            active_groups.append(group_name)
            tasks.append(_fetch_group(pool, vec_literal, present, n))

        results_per_group = await asyncio.gather(*tasks)

        candidates = []
        seen_ids: set = set()
        seen_sections: dict[str, int] = {}  # section_number → index in candidates
        for group_results in results_per_group:
            for chunk in group_results:
                chunk_id = chunk["id"]
                if chunk_id in seen_ids:
                    continue
                seen_ids.add(chunk_id)

                # Deduplicate by section_number: keep the highest-similarity
                # version.  Multiple ingest runs can create duplicate rows
                # with different IDs but identical content.
                sec = chunk.get("section_number", "")
                if sec and sec in seen_sections:
                    existing_idx = seen_sections[sec]
                    if chunk["similarity"] > candidates[existing_idx]["similarity"]:
                        candidates[existing_idx] = chunk
                    continue
                if sec:
                    seen_sections[sec] = len(candidates)
                candidates.append(chunk)

    if candidates:
        candidates = _rerank(candidates, query, vessel_profile)

    final = candidates[:limit]

    elapsed_ms = (time.perf_counter() - t0) * 1000
    logger.info(
        "Retrieval: %d candidates from %d group(s) → top %d in %.1fms",
        len(candidates),
        len(active_groups) if not sources else 1,
        len(final),
        elapsed_ms,
    )

    # Log each selected chunk for retrieval debugging
    if final:
        chunk_summaries = ", ".join(
            f"{c.get('source', '?')}/{c.get('section_number', '?')} ({c.get('_score', c.get('similarity', 0)):.3f})"
            for c in final
        )
        logger.info("Selected chunks: %s", chunk_summaries)

    return final


# ── Soft re-ranking ──────────────────────────────────────────────────────────


def _rerank(
    results: list[dict],
    query: str,
    vessel_profile: dict | None,
) -> list[dict]:
    """Apply vessel-profile + source-affinity + ERG-specific boosts and sort."""
    source_boosts = _source_affinity(query)

    profile_terms: list[str] = []
    if vessel_profile:
        if vessel_profile.get("vessel_type"):
            profile_terms.append(vessel_profile["vessel_type"].lower())
        if vessel_profile.get("route_type"):
            profile_terms.append(vessel_profile["route_type"].lower())
        for cargo in vessel_profile.get("cargo_types") or []:
            profile_terms.append(cargo.lower())

    logger.info(
        "Rerank: %d candidates, source_boosts=%s, profile_terms=%s",
        len(results), source_boosts or "{}", profile_terms or "[]",
    )

    # ERG-specific boosts: detect UN/NA numbers in query for cross-reference
    erg_active = "erg" in source_boosts
    query_un_numbers: list[str] = []
    if erg_active:
        query_un_numbers = [
            m.group().replace(" ", "").upper()
            for m in re.finditer(r"\b(?:UN|NA)\s*(\d{4})\b", query, re.IGNORECASE)
        ]
        # Also match bare 4-digit numbers that look like UN IDs (1000-9999)
        # only when ERG context is clear
        if not query_un_numbers:
            bare = re.findall(r"\b([1-9]\d{3})\b", query)
            query_un_numbers = [f"UN{n}" for n in bare if 1000 <= int(n) <= 3600]
        if query_un_numbers:
            logger.info("ERG UN/NA numbers in query: %s", query_un_numbers)

    for result in results:
        text_lower = (result.get("full_text") or "").lower()
        section = result.get("section_number", "")
        boost = 0.0

        # Vessel profile boost
        if profile_terms:
            boost += sum(0.05 for term in profile_terms if term in text_lower)

        # Source affinity boost
        if source_boosts:
            group = _SOURCE_TO_GROUP.get(result.get("source", ""), "")
            if group in source_boosts:
                boost += source_boosts[group]

        # ERG-specific: Orange Guide preference over Table chunks
        if erg_active and result.get("source") == "erg":
            if re.match(r"ERG Guide \d+", section):
                boost += 0.06
            elif re.match(r"ERG Table \d+", section):
                boost -= 0.03

        # ERG-specific: UN number cross-reference boost
        if query_un_numbers and result.get("source") == "erg":
            full_text = result.get("full_text") or ""
            for un in query_un_numbers:
                # Match both "UN1219" and bare "1219" in text
                bare_num = un.replace("UN", "").replace("NA", "")
                if un in full_text.upper() or bare_num in full_text:
                    boost += 0.12
                    break  # one match is enough

        result["_score"] = float(result["similarity"]) + boost

        if boost > 0:
            logger.debug(
                "Boost %s: sim=%.3f +%.3f → %.3f",
                section, float(result["similarity"]), boost, result["_score"],
            )

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results

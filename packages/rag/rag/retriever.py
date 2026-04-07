"""
pgvector semantic search with soft re-ranking.

Fetch strategy:
  - Always fetch a wider pool (top _RERANK_POOL_SIZE) so the re-rank pass has
    room to promote chunks that score higher under the boost rules.
  - Re-rank applies two soft boosts:
      1. Source-affinity: when the query mentions COLREGs / nav-rule keywords,
         boost chunks from the `colregs` source so they aren't outranked by
         semantically-similar 33 CFR or 49 CFR content.
      2. Vessel profile: when a vessel_profile is provided, boost chunks whose
         text contains the vessel's type / route / cargo terms.
  - The two boosts are additive. The final list is sorted by (similarity + boost)
    and the top `limit` are returned.
"""

import logging
import re

import asyncpg
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_RERANK_POOL_SIZE = 20  # fetch this many before re-ranking

# ── COLREGs / navigation-rule source affinity ──────────────────────────────
#
# When the query unambiguously references COLREGs or one of the rule numbers
# (Rules 1-38, Annexes I-V), we boost the score of `colregs` source chunks so
# they aren't outranked by semantically-similar 33 CFR Subchapter E or 49 CFR
# rail-collision content.
#
# Each keyword match adds _COLREGS_BOOST_PER_MATCH; the total per chunk is
# capped at _COLREGS_MAX_BOOST to prevent runaway boosting on long queries.

_COLREGS_KEYWORDS: tuple[str, ...] = (
    # Direct mentions
    "colreg",
    "collision regulation",
    "rules of the road",
    "rule of the road",
    "72 colregs",
    # Behavior rules
    "head-on",
    "head on situation",
    "crossing situation",
    "overtaking",
    "give-way",
    "give way vessel",
    "stand-on",
    "stand on vessel",
    "look-out",
    "lookout",
    "risk of collision",
    "narrow channel",
    "traffic separation",
    "restricted visibility",
    # Light & sound rules
    "navigation light",
    "navigation lights",
    "masthead light",
    "sidelight",
    "side light",
    "stern light",
    "anchor light",
    "fog signal",
    "sound signal",
    "manoeuvring signal",
    "maneuvering signal",
    "whistle signal",
)
_COLREGS_RULE_RE = re.compile(r"\brule\s*([0-9]{1,2})\b", re.IGNORECASE)
_COLREGS_ANNEX_RE = re.compile(r"\bannex\s*([ivx]+|[0-9])\b", re.IGNORECASE)
_COLREGS_BOOST_PER_MATCH = 0.15
_COLREGS_MAX_BOOST = 0.30
# When the query has any COLREGs affinity, also fetch the top-N colregs-source
# chunks and merge them into the pool. Without this safety net, COLREGs chunks
# whose raw similarity falls outside the global top _RERANK_POOL_SIZE never get
# a chance to be boosted (e.g., "how do I determine risk of collision?", which
# is dominated by 49 CFR rail-collision content).
_COLREGS_SUPPLEMENTAL_LIMIT = 10


def _colregs_boost_for_query(query: str) -> float:
    """Return the COLREGs source-affinity boost amount for this query.

    Returns 0.0 when the query has no COLREGs or rule-number keywords.
    """
    q = query.lower()
    matches = sum(1 for kw in _COLREGS_KEYWORDS if kw in q)
    if _COLREGS_RULE_RE.search(q):
        matches += 1
    if _COLREGS_ANNEX_RE.search(q):
        matches += 1
    if matches == 0:
        return 0.0
    return min(_COLREGS_BOOST_PER_MATCH * matches, _COLREGS_MAX_BOOST)


async def retrieve(
    query: str,
    pool: asyncpg.Pool,
    openai_api_key: str,
    vessel_profile: dict | None = None,
    limit: int = 8,
    sources: list[str] | None = None,
) -> list[dict]:
    """Return semantically relevant regulation chunks, optionally re-ranked by vessel profile.

    Args:
        query:          The user's question.
        pool:           asyncpg connection pool.
        openai_api_key: Key for OpenAI embeddings API.
        vessel_profile: Dict with optional keys vessel_type, route_type, cargo_types (list).
        limit:          Maximum chunks to return after re-ranking.
        sources:        Restrict search to these source values (e.g. ['cfr_46']).

    Returns:
        List of dicts: id, source, section_number, section_title, full_text, similarity.
    """
    # 1. Embed query
    oai = AsyncOpenAI(api_key=openai_api_key)
    try:
        resp = await oai.embeddings.create(model=_EMBED_MODEL, input=[query])
    finally:
        await oai.close()

    embedding = resp.data[0].embedding
    vec_literal = "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

    # 2. Build SQL — optional source filter. Always fetch a wider pool so
    # the re-rank pass below can promote boost-eligible chunks.
    fetch_limit = max(_RERANK_POOL_SIZE, limit)

    if sources:
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
    else:
        rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM regulations
            WHERE embedding IS NOT NULL
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_literal,
            fetch_limit,
        )

    results = [dict(row) for row in rows]

    # 2b. Supplemental COLREGs fetch — guarantee colregs chunks are eligible
    # for boosting when the query has navigation-rule affinity. Skipped if the
    # caller already restricted `sources` (the explicit filter wins).
    if not sources and _colregs_boost_for_query(query) > 0:
        extra_rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   1 - (embedding <=> $1::vector) AS similarity
            FROM regulations
            WHERE embedding IS NOT NULL
              AND source = 'colregs'
            ORDER BY embedding <=> $1::vector
            LIMIT $2
            """,
            vec_literal,
            _COLREGS_SUPPLEMENTAL_LIMIT,
        )
        seen_ids = {r["id"] for r in results}
        for row in extra_rows:
            if row["id"] not in seen_ids:
                results.append(dict(row))
                seen_ids.add(row["id"])
        logger.info(
            "COLREGs supplemental fetch: pool grew to %d chunks",
            len(results),
        )

    # 3. Soft re-ranking (COLREGs source affinity + optional vessel profile)
    if results:
        results = _rerank(results, query, vessel_profile)

    return results[:limit]


def _rerank(
    results: list[dict],
    query: str,
    vessel_profile: dict | None,
) -> list[dict]:
    """Apply soft boosts and resort:

    1. COLREGs source-affinity: when the query mentions navigation-rule
       keywords, boost `colregs`-source chunks by up to _COLREGS_MAX_BOOST.
    2. Vessel profile: when a vessel profile is provided, boost chunks
       whose full_text contains the vessel's type / route / cargo terms.
    """
    colregs_boost = _colregs_boost_for_query(query)

    profile_terms: list[str] = []
    if vessel_profile:
        if vessel_profile.get("vessel_type"):
            profile_terms.append(vessel_profile["vessel_type"].lower())
        if vessel_profile.get("route_type"):
            profile_terms.append(vessel_profile["route_type"].lower())
        for cargo in vessel_profile.get("cargo_types") or []:
            profile_terms.append(cargo.lower())

    if colregs_boost:
        logger.info("COLREGs source boost applied: +%.2f", colregs_boost)

    for result in results:
        text_lower = (result.get("full_text") or "").lower()
        boost = 0.0
        if profile_terms:
            boost += sum(0.05 for term in profile_terms if term in text_lower)
        if colregs_boost and result.get("source") == "colregs":
            boost += colregs_boost
        result["_score"] = float(result["similarity"]) + boost

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results

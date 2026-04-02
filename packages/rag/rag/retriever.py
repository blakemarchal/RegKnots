"""
pgvector semantic search with soft vessel profile re-ranking.

Fetch strategy:
  - No vessel profile: fetch top `limit` directly.
  - With vessel profile: fetch top 20, boost chunks where section text
    contains vessel profile terms (+0.05 per matched field), return top `limit`.
"""

import logging

import asyncpg
from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_VESSEL_FETCH_MULTIPLIER = 20  # fetch this many before re-ranking


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

    # 2. Build SQL — optional source filter
    fetch_limit = _VESSEL_FETCH_MULTIPLIER if vessel_profile else limit

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

    # 3. Soft vessel profile re-ranking
    if vessel_profile and results:
        results = _rerank(results, vessel_profile)

    return results[:limit]


def _rerank(results: list[dict], vessel_profile: dict) -> list[dict]:
    """Boost chunks whose full_text contains vessel profile terms."""
    boost_terms: list[str] = []

    if vessel_profile.get("vessel_type"):
        boost_terms.append(vessel_profile["vessel_type"].lower())
    if vessel_profile.get("route_type"):
        boost_terms.append(vessel_profile["route_type"].lower())
    for cargo in vessel_profile.get("cargo_types") or []:
        boost_terms.append(cargo.lower())

    for result in results:
        text_lower = (result.get("full_text") or "").lower()
        boost = sum(0.05 for term in boost_terms if term in text_lower)
        result["_score"] = float(result["similarity"]) + boost

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results

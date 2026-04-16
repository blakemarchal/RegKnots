"""
Hybrid semantic + keyword retriever with source-diversified fetch.

Retrieval strategy:

1. Embed the query once.
2. Detect regulation identifiers in the query (UN numbers, CFR sections,
   COLREGs rules, etc.) and run keyword search for matching chunks.
3. Run one vector search per configured source group, CONCURRENTLY. Each
   group gets its own top-N candidate pool, so small sources (COLREGs: 102,
   SOLAS: 742) aren't outranked by large ones (CFR: ~33K chunks) just
   because the large sources have more chunks to draw from.
4. Merge keyword results into vector results, deduplicate by section_number.
5. Apply two soft boosts:
     - Source affinity: when the query unambiguously targets a source
       (e.g., mentions COLREGs, 46 CFR, SOLAS chapter, STCW), boost chunks
       from that source's group.
     - Vessel profile: when a vessel_profile is provided, boost chunks
       whose full_text mentions the vessel's type / route / cargo.
6. Sort by similarity + boosts, return top `limit`.

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
    "ism": ("ism", "ism_supplement"),
    "erg": ("erg",),
    "nmc": ("nmc_memo",),
}

# Per-group candidate pool sizes. CFR is larger because it covers three
# sub-titles (~33K total chunks) and needs room for intra-CFR diversity.
_CANDIDATES_PER_GROUP: dict[str, int] = {
    "cfr": 12,
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
    "voyage data recorder", "lrit",
    "global maritime distress", "gmdss",
)
_SOLAS_ABBR_RE = re.compile(r"\b(?:vdr|s-vdr|epirb|sart)\b", re.IGNORECASE)

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

# NMC (National Maritime Center) — credentialing, medical certificates,
# MMC processing, endorsements. These terms boost nmc_memo results.
_NMC_TERMS: tuple[str, ...] = (
    "nmc", "national maritime center",
    "merchant mariner credential", "mmc renewal", "mmc application",
    "medical certificate", "medical waiver", "cg-719", "cg719",
    "credential renewal", "credential application", "credential upgrade",
    "endorsement", "sea service", "sea time",
    "processing time", "evaluation time",
    "twic", "transportation worker",
    "mariner credential", "mariner license",
    "drug test", "physical exam",
    "stcw endorsement", "officer endorsement",
    "raise of grade", "raise in grade",
)
_NMC_ABBR_RE = re.compile(r"\b(?:nmc|mmc|twic|cg-?719)\b", re.IGNORECASE)


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

    if any(t in q for t in _SOLAS_TERMS) or _SOLAS_ABBR_RE.search(q):
        boosts["solas"] = 0.20

    if any(t in q for t in _STCW_TERMS):
        boosts["stcw"] = 0.20

    if any(t in q for t in _NVIC_TERMS):
        boosts["nvic"] = 0.20

    if any(t in q for t in _ISM_TERMS) or _ISM_ABBR_RE.search(q):
        boosts["ism"] = 0.20

    if any(t in q for t in _ERG_TERMS) or _ERG_ABBR_RE.search(q):
        boosts["erg"] = 0.20

    if any(t in q for t in _NMC_TERMS) or _NMC_ABBR_RE.search(q):
        boosts["nmc"] = 0.20
        # Credentialing queries also benefit from CFR Parts 10-16
        boosts.setdefault("cfr", 0.10)

    if "cfr" in q or "code of federal" in q:
        boosts["cfr"] = 0.15
        if any(
            t in q
            for t in ("33 cfr", "title 33", "46 cfr", "title 46", "49 cfr", "title 49")
        ):
            boosts["cfr"] = 0.25

    return boosts


# ── Identifier detection (source-agnostic) ────────────────────────────────
#
# Scans the query for known regulation identifier patterns. These are
# arbitrary strings (UN1219, 46 CFR 35.10-5, Rule 14) with no semantic
# meaning — vector search cannot match them, so we fall back to keyword
# search when they are detected.

_IDENTIFIER_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("un_number",    re.compile(r"\b(UN|NA)(\d{4})\b", re.IGNORECASE)),
    ("erg_guide",    re.compile(r"\b(?:ERG\s+)?Guide\s+(\d{3})\b", re.IGNORECASE)),
    ("cfr_section",  re.compile(r"\b(\d{1,2})\s*CFR\s*([\d.]+(?:-[\d]+)?)\b", re.IGNORECASE)),
    ("colregs_rule", re.compile(r"\b(?:COLREGs?\s+)?Rule\s+(\d{1,2})\b", re.IGNORECASE)),
    ("solas_reg",    re.compile(r"\bSOLAS\s+(Ch\.?)?([IVX]+-\d+)(?:\s*(?:Reg\.?\s*|/)(\d+))?\b", re.IGNORECASE)),
    ("nvic_number",  re.compile(r"\bNVIC\s+(\d{2}-\d{2})\b", re.IGNORECASE)),
    ("ism_section",  re.compile(r"\bISM\s+(?:Code\s+)?(\d+(?:\.\d+)?)\b", re.IGNORECASE)),
]


def _extract_identifiers(query: str) -> list[dict]:
    """Scan query for known regulation identifier patterns.

    Returns a list of dicts with keys: type, value, pattern.
    The 'pattern' field is the substring used for database text search.
    """
    identifiers: list[dict] = []
    for id_type, regex in _IDENTIFIER_PATTERNS:
        for m in regex.finditer(query):
            if id_type == "un_number":
                prefix = m.group(1).upper()
                number = m.group(2)
                identifiers.append({
                    "type": id_type,
                    "value": f"{prefix}{number}",
                    "pattern": f"{prefix}{number}",
                })
            elif id_type == "erg_guide":
                identifiers.append({
                    "type": id_type,
                    "value": f"Guide {m.group(1)}",
                    "pattern": f"Guide {m.group(1)}",
                })
            elif id_type == "cfr_section":
                title = m.group(1)
                section = m.group(2)
                identifiers.append({
                    "type": id_type,
                    "value": f"{title} CFR {section}",
                    "pattern": section,
                })
            elif id_type == "colregs_rule":
                identifiers.append({
                    "type": id_type,
                    "value": f"Rule {m.group(1)}",
                    "pattern": f"Rule {m.group(1)}",
                })
            elif id_type == "solas_reg":
                identifiers.append({
                    "type": id_type,
                    "value": m.group(0),
                    "pattern": m.group(2),  # e.g. "II-2"
                })
            elif id_type == "nvic_number":
                identifiers.append({
                    "type": id_type,
                    "value": f"NVIC {m.group(1)}",
                    "pattern": m.group(1),
                })
            elif id_type == "ism_section":
                identifiers.append({
                    "type": id_type,
                    "value": f"ISM {m.group(1)}",
                    "pattern": m.group(1),
                })
    return identifiers


# ── Broad keyword extraction ───────────────────────────────────────────────
#
# Extracts substantive search terms from ANY query by stripping stopwords.
# These keywords are searched with lower confidence than identifiers, but
# they close the gap for queries like "chlorine gas" or "ammonia leak"
# where no formal identifier is present.

_STOPWORDS: frozenset[str] = frozenset(
    # articles / prepositions
    "the a an for of on in to from with by at about"
    # question / auxiliary words
    " what which how where when who does do is are was were can could"
    " should would will may might shall"
    # common verbs
    " require explain describe tell show give need help find handle"
    " apply cover covers mean uses using used have been"
    # domain-generic words (appear in nearly every chunk)
    " requirements regulations rules procedures vessel vessels ship ships"
    " aboard maritime marine must compliance section chapter part"
    " regulation rule code standard safety international"
    # source names (already handled by source affinity)
    " solas colregs stcw nvic guide emergency response".split()
)

_MAX_KEYWORD_TERMS = 4
_MIN_KEYWORD_LEN = 4
_MAX_KEYWORD_FREQ = 200  # Skip keywords appearing in > this many chunks


def _extract_keywords(query: str) -> list[str]:
    """Extract substantive search terms from query after stripping stopwords.

    Returns up to _MAX_KEYWORD_TERMS keywords, longest first (longer words
    are more specific). Only words with _MIN_KEYWORD_LEN+ characters are
    kept.
    """
    # Tokenize: keep only alphabetic words (drop numbers, punctuation)
    words = re.findall(r"[a-zA-Z]+", query.lower())
    keywords = [
        w for w in words
        if len(w) >= _MIN_KEYWORD_LEN and w not in _STOPWORDS
    ]
    # Deduplicate preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            unique.append(w)
    # Take longest first — more specific, fewer false positives
    unique.sort(key=len, reverse=True)
    return unique[:_MAX_KEYWORD_TERMS]


# ── Query embedding ──────────────────────────────────────────────────────────


async def _embed_query(openai_api_key: str, query: str) -> str:
    oai = AsyncOpenAI(api_key=openai_api_key)
    try:
        resp = await oai.embeddings.create(model=_EMBED_MODEL, input=[query])
    finally:
        await oai.close()
    embedding = resp.data[0].embedding
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


# ── Keyword search (identifier + broad keyword) ─────────────────────────────


async def _identifier_search(
    identifiers: list[dict],
    pool: asyncpg.Pool,
    limit: int = 5,
) -> list[dict]:
    """Search regulations by text for structured identifiers (high confidence).

    Returns results in the same dict format as vector search.
    """
    results: list[dict] = []
    seen_ids: set = set()
    for ident in identifiers:
        rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   0.0 AS similarity
            FROM regulations
            WHERE full_text ILIKE '%' || $1 || '%'
            LIMIT $2
            """,
            ident["pattern"],
            limit,
        )
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                results.append(dict(r))
    return results


async def _broad_keyword_search(
    keywords: list[str],
    pool: asyncpg.Pool,
    limit: int = 5,
) -> tuple[list[dict], list[str]]:
    """Search regulations by text for broad keywords (lower confidence).

    Uses the GIN trigram index for fast ILIKE lookups. Returns up to
    `limit` source-diversified results per keyword (at most one per
    source via DISTINCT ON), plus the list of keywords that passed the
    frequency cap (used by the caller for in-memory candidate boosting).

    Keywords appearing in more than _MAX_KEYWORD_FREQ chunks are skipped
    as too common to be useful (e.g., "fire" appears in hundreds of
    chunks across sources).

    Source diversity: uses DISTINCT ON (source) so each source contributes
    at most one result per keyword — the chunk with the most keyword
    occurrences. This mirrors the diversified vector search architecture
    and prevents any single large source (e.g., CFR with 33K chunks) from
    monopolizing keyword results.
    """
    results: list[dict] = []
    seen_ids: set = set()
    passed_keywords: list[str] = []
    for kw in keywords:
        # Fast specificity check: skip overly common terms.
        freq = await pool.fetchval(
            """
            SELECT count(*) FROM (
                SELECT 1 FROM regulations
                WHERE full_text ILIKE '%' || $1 || '%'
                LIMIT $2
            ) sub
            """,
            kw,
            _MAX_KEYWORD_FREQ + 1,
        )
        if freq > _MAX_KEYWORD_FREQ:
            logger.info(
                "Keyword '%s' matches > %d chunks — too common, skipping",
                kw, _MAX_KEYWORD_FREQ,
            )
            continue

        passed_keywords.append(kw)

        rows = await pool.fetch(
            """
            SELECT id, source, section_number, section_title, full_text,
                   0.0 AS similarity
            FROM (
                SELECT DISTINCT ON (source)
                    id, source, section_number, section_title, full_text
                FROM regulations
                WHERE full_text ILIKE '%' || $1 || '%'
                ORDER BY source,
                         (length(full_text)
                          - length(replace(lower(full_text), lower($1), ''))
                         ) DESC
            ) sub
            ORDER BY (length(full_text)
                      - length(replace(lower(full_text), lower($1), ''))
                     ) DESC
            LIMIT $2
            """,
            kw,
            limit,
        )
        for r in rows:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                results.append(dict(r))
    return results, passed_keywords


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

    # ── Hybrid merge: two-tier keyword search ────────────────────────────
    #
    # Tier 1 (identifiers): structured patterns like UN1219, Rule 14.
    #   Synthetic score = max_sim + 0.05 (highest confidence).
    # Tier 2 (broad keywords): substantive terms like "chlorine", "ammonia".
    #   Synthetic score = max_sim + 0.02 (literal text match = strong signal).
    #
    # In-memory keyword boost: vector search may have found the right
    # chunk (e.g., ERG Guide 124) but ranked it low.  The ILIKE query
    # may not return it either (source-diversified results pick the best
    # chunk per source, which might be an index chunk rather than a guide).
    # So we also scan existing vector candidates for keyword text matches
    # and boost their scores directly — zero DB cost.
    #
    # Both tiers dedup by section_number against vector results.
    # When a keyword-matched chunk is already in the pool (same
    # section_number), we BOOST the existing chunk's similarity to the
    # keyword synthetic score instead of silently discarding the signal.
    identifiers = _extract_identifiers(query)
    keywords = _extract_keywords(query)

    id_results: list[dict] = []
    kw_results: list[dict] = []
    specific_keywords: list[str] = []
    if identifiers:
        id_results = await _identifier_search(identifiers, pool)
    if keywords:
        kw_results, specific_keywords = await _broad_keyword_search(keywords, pool)

    max_sim = max(
        (float(c["similarity"]) for c in candidates),
        default=0.0,
    ) if candidates else 0.0

    # ── In-memory keyword boost ────────────────────────────────────────
    #
    # Scan vector candidates for keyword text matches and boost scores.
    # Only uses keywords that passed the frequency cap (specific_keywords),
    # so common words like "fire" (3453 matches) don't trigger boosting.
    if specific_keywords:
        kw_boost_sim = max_sim + 0.02
        kw_mem_boosted = 0
        for c in candidates:
            if float(c["similarity"]) >= kw_boost_sim:
                continue
            text_lower = (c.get("full_text") or "").lower()
            if any(kw in text_lower for kw in specific_keywords):
                c["similarity"] = kw_boost_sim
                kw_mem_boosted += 1
        if kw_mem_boosted:
            logger.info(
                "In-memory keyword boost: %d candidates boosted for %s",
                kw_mem_boosted, specific_keywords,
            )

    if id_results or kw_results:

        existing_sections = {
            c.get("section_number", "")
            for c in candidates
            if c.get("section_number")
        }
        existing_ids = {c["id"] for c in candidates}

        id_added = 0
        kw_added = 0
        id_boosted = 0
        kw_boosted = 0

        def _merge_chunks(
            chunks: list[dict], synthetic_sim: float, counter_name: str,
        ) -> tuple[int, int]:
            added = 0
            boosted = 0
            for chunk in chunks:
                sec = chunk.get("section_number", "")
                if chunk["id"] in existing_ids:
                    continue
                if sec and sec in existing_sections:
                    # Score override: boost existing chunk if keyword
                    # score is higher than its vector similarity.
                    idx = seen_sections.get(sec)
                    if idx is not None and synthetic_sim > float(candidates[idx]["similarity"]):
                        candidates[idx]["similarity"] = synthetic_sim
                        boosted += 1
                    continue
                chunk["similarity"] = synthetic_sim
                candidates.append(chunk)
                if sec:
                    existing_sections.add(sec)
                    seen_sections[sec] = len(candidates) - 1
                existing_ids.add(chunk["id"])
                added += 1
            return added, boosted

        if id_results:
            id_added, id_boosted = _merge_chunks(id_results, max_sim + 0.05, "identifier")
        if kw_results:
            kw_added, kw_boosted = _merge_chunks(kw_results, max_sim + 0.02, "keyword")

        logger.info(
            "Hybrid merge: %d identifier matches for %s, "
            "%d keyword matches for %s, %d added / %d boosted",
            len(id_results),
            [i["value"] for i in identifiers] if identifiers else "[]",
            len(kw_results),
            keywords or "[]",
            id_added + kw_added,
            id_boosted + kw_boosted,
        )

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
    """Apply vessel-profile + source-affinity boosts and sort."""
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

    for result in results:
        text_lower = (result.get("full_text") or "").lower()
        boost = 0.0

        # Vessel profile boost
        if profile_terms:
            boost += sum(0.05 for term in profile_terms if term in text_lower)

        # Source affinity boost
        if source_boosts:
            group = _SOURCE_TO_GROUP.get(result.get("source", ""), "")
            if group in source_boosts:
                boost += source_boosts[group]

        result["_score"] = float(result["similarity"]) + boost

        if boost > 0:
            logger.debug(
                "Boost %s: sim=%.3f +%.3f → %.3f",
                result.get("section_number", ""),
                float(result["similarity"]),
                boost,
                result["_score"],
            )

    results.sort(key=lambda x: x["_score"], reverse=True)
    return results

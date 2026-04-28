"""
asyncpg database operations for the ingest pipeline.

Upsert key: (source, section_number, chunk_index) — enforced by
idx_regulations_unique_chunk (added in migration 0002).

Embeddings are serialised to the pgvector literal "[x,x,x,...]"
format and cast with ::vector in the SQL, avoiding a runtime codec dep.
"""

import logging
from datetime import date

import asyncpg

from ingest.models import EmbeddedChunk, TITLE_NAMES

logger = logging.getLogger(__name__)

_UPSERT_SQL = """
    INSERT INTO regulations (
        source, source_version, title, section_number, section_title,
        full_text, chunk_index, embedding, up_to_date_as_of, content_hash,
        published_date, expires_date, superseded_by, jurisdictions
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10, $11, $12, $13, $14::text[])
    ON CONFLICT (source, section_number, chunk_index) DO UPDATE SET
        source_version   = EXCLUDED.source_version,
        section_title    = EXCLUDED.section_title,
        full_text        = EXCLUDED.full_text,
        embedding        = EXCLUDED.embedding,
        up_to_date_as_of = EXCLUDED.up_to_date_as_of,
        content_hash     = EXCLUDED.content_hash,
        published_date   = EXCLUDED.published_date,
        expires_date     = EXCLUDED.expires_date,
        superseded_by    = EXCLUDED.superseded_by,
        jurisdictions    = EXCLUDED.jurisdictions
    WHERE regulations.content_hash IS DISTINCT FROM EXCLUDED.content_hash
       OR regulations.jurisdictions IS DISTINCT FROM EXCLUDED.jurisdictions
"""

_BATCH_SIZE = 500


async def get_previous_as_of(pool: asyncpg.Pool, source: str) -> date | None:
    """Return the most recent up_to_date_as_of already stored for this source."""
    val = await pool.fetchval(
        "SELECT up_to_date_as_of FROM regulations WHERE source = $1 LIMIT 1",
        source,
    )
    return val


async def get_existing_chunk_count(pool: asyncpg.Pool, source: str) -> int:
    """Return the number of chunks currently stored for a source."""
    val = await pool.fetchval(
        "SELECT count(*) FROM regulations WHERE source = $1",
        source,
    )
    return int(val or 0)


async def get_existing_hashes(pool: asyncpg.Pool, source: str) -> set[str]:
    """Return all non-null content_hash values stored for this source."""
    rows = await pool.fetch(
        "SELECT content_hash FROM regulations "
        "WHERE source = $1 AND content_hash IS NOT NULL",
        source,
    )
    return {row["content_hash"] for row in rows}


async def upsert_chunks(pool: asyncpg.Pool, chunks: list[EmbeddedChunk]) -> int:
    """Upsert embedded chunks into the regulations table.

    Returns the number of rows sent (not the count of rows actually changed —
    asyncpg's executemany does not expose per-row affected counts).
    """
    if not chunks:
        return 0

    total = 0
    async with pool.acquire() as conn:
        for i in range(0, len(chunks), _BATCH_SIZE):
            batch = chunks[i : i + _BATCH_SIZE]
            rows = [_to_row(c) for c in batch]
            await conn.executemany(_UPSERT_SQL, rows)
            total += len(batch)

    return total


async def record_version_change(
    pool: asyncpg.Pool,
    source: str,
    previous_as_of: date,
    new_as_of: date,
    changed_section_numbers: list[str],
) -> None:
    """Insert a regulation_versions row recording the detected change."""
    await pool.execute(
        """
        INSERT INTO regulation_versions
            (source, previous_version, new_version, changed_sections)
        VALUES ($1, $2, $3, $4)
        """,
        source,
        previous_as_of.isoformat(),
        new_as_of.isoformat(),
        changed_section_numbers,
    )
    logger.info(
        f"Recorded version change: {source} "
        f"{previous_as_of} → {new_as_of} "
        f"({len(changed_section_numbers)} sections)"
    )


# ── Row serialisation ────────────────────────────────────────────────────────

def _to_row(c: EmbeddedChunk) -> tuple:
    # Sprint D6.19 — derive jurisdictions from source.
    juris = _jurisdictions_for_source(c.source)
    return (
        c.source,
        c.up_to_date_as_of.isoformat(),          # source_version
        TITLE_NAMES[c.title_number],             # title
        c.section_number,
        c.section_title,
        c.chunk_text,                            # full_text
        c.chunk_index,
        _vec(c.embedding),                       # embedding as pgvector literal
        c.up_to_date_as_of,
        c.content_hash,
        c.published_date,                        # nullable freshness column
        c.expires_date,                          # nullable freshness column
        c.superseded_by,                         # nullable freshness column
        juris,                                   # jurisdictions text[]
    )


def _vec(embedding: list[float]) -> str:
    """Serialise a float list to pgvector literal format: '[x,x,...]'"""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"


# Sprint D6.19 — source → jurisdiction tags. KEEP IN SYNC with
#   apps/api/alembic/versions/0058_add_jurisdictions_column.py
#   packages/rag/rag/jurisdiction.py SOURCE_TO_JURISDICTIONS
# All three are authoritative for their layer (DB on backfill, retriever
# on read, ingest on write). Adding a new source means updating all three.
_SOURCE_TO_JURISDICTIONS: dict[str, list[str]] = {
    # US national
    "cfr_33":           ["us"],
    "cfr_46":           ["us"],
    "cfr_49":           ["us"],
    "usc_46":           ["us"],
    "nvic":             ["us"],
    "nmc_policy":       ["us"],
    "nmc_checklist":    ["us"],
    "uscg_msm":         ["us"],
    "uscg_bulletin":    ["us"],
    # UK national
    "mca_mgn":          ["uk"],
    "mca_msn":          ["uk"],
    # Australian national
    "amsa_mo":          ["au"],
    # Liberian (LISCR) national
    "liscr_mn":         ["lr"],
    # Marshall Islands (IRI) national
    "iri_mn":           ["mh"],
    # Singapore (Sprint D6.22)
    "mpa_sc":           ["sg"],
    # Hong Kong (Sprint D6.22)
    "mardep_msin":      ["hk"],
    # Canada (Sprint D6.22)
    "tc_ssb":           ["ca"],
    # Bahamas (Sprint D6.22)
    "bma_mn":           ["bs"],
    # International (universal)
    "solas":            ["intl"],
    "solas_supplement": ["intl"],
    "colregs":          ["intl"],
    "stcw":             ["intl"],
    "stcw_supplement":  ["intl"],
    "ism":              ["intl"],
    "ism_supplement":   ["intl"],
    "marpol":           ["intl"],
    "marpol_supplement":["intl"],
    "imdg":             ["intl"],
    "imdg_supplement":  ["intl"],
    "who_ihr":          ["intl"],
    # ERG — US DOT publication, internationally referenced; dual-tagged.
    "erg":              ["us", "intl"],
}


def _jurisdictions_for_source(source: str) -> list[str]:
    """Default to ['intl'] when an unknown source is encountered.

    Unknown source-defaulted to a non-empty array (rather than []) so
    the chunk is never accidentally invisible — '∅ && X' is always
    false, which would suppress under every allow-set.
    """
    return _SOURCE_TO_JURISDICTIONS.get(source, ["intl"])

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
        full_text, chunk_index, embedding, up_to_date_as_of, content_hash
    )
    VALUES ($1, $2, $3, $4, $5, $6, $7, $8::vector, $9, $10)
    ON CONFLICT (source, section_number, chunk_index) DO UPDATE SET
        source_version   = EXCLUDED.source_version,
        section_title    = EXCLUDED.section_title,
        full_text        = EXCLUDED.full_text,
        embedding        = EXCLUDED.embedding,
        up_to_date_as_of = EXCLUDED.up_to_date_as_of,
        content_hash     = EXCLUDED.content_hash
    WHERE regulations.content_hash IS DISTINCT FROM EXCLUDED.content_hash
"""

_BATCH_SIZE = 500


async def get_previous_as_of(pool: asyncpg.Pool, source: str) -> date | None:
    """Return the most recent up_to_date_as_of already stored for this source."""
    val = await pool.fetchval(
        "SELECT up_to_date_as_of FROM regulations WHERE source = $1 LIMIT 1",
        source,
    )
    return val


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
    )


def _vec(embedding: list[float]) -> str:
    """Serialise a float list to pgvector literal format: '[x,x,...]'"""
    return "[" + ",".join(f"{x:.8f}" for x in embedding) + "]"

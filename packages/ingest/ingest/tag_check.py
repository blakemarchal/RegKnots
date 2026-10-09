"""Stored jurisdiction tags vs the code map (2026-10-08).

COSWP carried ['intl'] for four months: `ingest.store._SOURCE_TO_JURISDICTIONS`
gained `coswp -> ["uk"]` after its only ingest, and tags are written only when a
row is ingested, so a UK code reached U.S.-flag answers (the Captain's manila
hedge, 2026-10-08). scripts/deploy.sh runs this on every deploy; it reports
drift and never fails the deploy.

    uv run python -m ingest.tag_check
"""
from __future__ import annotations

import asyncio
import sys

import asyncpg

from ingest.config import settings
from ingest.store import _jurisdictions_for_source


def drift(rows) -> list[tuple[str, list[str], list[str], int]]:
    """(source, stored, expected, rows) for every group whose stored tags differ."""
    return [(r["source"], list(r["jurisdictions"] or []), _jurisdictions_for_source(r["source"]), r["n"])
            for r in rows if list(r["jurisdictions"] or []) != _jurisdictions_for_source(r["source"])]


async def main() -> int:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT source, jurisdictions, count(*) AS n FROM regulations GROUP BY 1, 2")
    finally:
        await conn.close()
    bad = drift(rows)
    if not bad:
        print(f"jurisdiction tags: ok ({len({r['source'] for r in rows})} sources)")
        return 0
    for source, stored, expected, n in bad:
        print(f"WARNING jurisdiction drift: {source} stored={stored} code={expected} rows={n} "
              f"(re-ingest the source, or UPDATE regulations SET jurisdictions = ... WHERE source = '{source}')")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

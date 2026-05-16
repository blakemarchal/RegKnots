"""Backfill vessels.classification_society from the IACS lookup table.

Sprint D6.94 — for existing vessels with imo_mmsi set but no
classification_society, runs a one-shot UPDATE that joins
iacs_ships_in_class on the parsed IMO and writes
``classification_society = isc.society_normalized`` with
``classification_society_source = 'iacs_lookup'``.

Idempotent — only fills NULLs, never overrides a user-set value.

Run once after deploying D6.94 (migrations 0100+0101 +
refresh_iacs_ships_in_class.py). After that the per-create / per-PUT
auto-populate path handles new vessels; this script is for the
existing-data backfill.

Usage:
    uv run python scripts/backfill_classification_society.py
    uv run python scripts/backfill_classification_society.py --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("class_society_backfill")


_BACKFILL_SQL = """
    UPDATE vessels v
    SET classification_society = isc.society_normalized,
        classification_society_source = 'iacs_lookup'
    FROM iacs_ships_in_class isc
    WHERE v.classification_society IS NULL
      AND v.imo_mmsi ~ '^(IMO[[:space:]]*)?[0-9]{7}$'
      AND isc.imo = (regexp_replace(v.imo_mmsi, '^IMO[[:space:]]*', ''))::bigint
      AND isc.society_normalized IS NOT NULL
    RETURNING v.name, v.imo_mmsi, v.classification_society
"""

_DRY_RUN_SQL = """
    SELECT v.name, v.imo_mmsi, isc.society_normalized AS would_set
    FROM vessels v
    JOIN iacs_ships_in_class isc
        ON isc.imo = (regexp_replace(v.imo_mmsi, '^IMO[[:space:]]*', ''))::bigint
    WHERE v.classification_society IS NULL
      AND v.imo_mmsi ~ '^(IMO[[:space:]]*)?[0-9]{7}$'
      AND isc.society_normalized IS NOT NULL
    ORDER BY v.name
"""


async def _async_main(args) -> int:
    dsn = args.database_url.replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(dsn)
    try:
        if args.dry_run:
            rows = await conn.fetch(_DRY_RUN_SQL)
            logger.info("dry-run — would update %d vessel(s):", len(rows))
            for r in rows:
                logger.info(
                    "  %s (imo=%s) → %s",
                    r["name"], r["imo_mmsi"], r["would_set"],
                )
            return 0

        rows = await conn.fetch(_BACKFILL_SQL)
        logger.info("Updated %d vessel(s) via IACS lookup:", len(rows))
        for r in rows:
            logger.info(
                "  %s (imo=%s) → %s",
                r["name"], r["imo_mmsi"], r["classification_society"],
            )
        return 0
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would be updated, no DB writes.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://regknots:regknots@localhost:5432/regknots"),
        help="Postgres DSN (default reads DATABASE_URL env var).",
    )
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())

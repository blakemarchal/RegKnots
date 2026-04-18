"""Post-ingest report for the uscg_bulletin source.

Consumes data/raw/uscg_bulletins/ingest_stats.json (written by the
adapter at the end of its fetch loop) and the live regulations table,
produces a structured summary for the sprint final report.
"""
from __future__ import annotations

import asyncio
import json
import sys
from collections import Counter
from pathlib import Path

import asyncpg

sys.path.insert(0, "/opt/RegKnots/packages/ingest")
sys.path.insert(0, "/opt/RegKnots/apps/api")
from app.config import settings as api_settings

STATS_PATH = Path("/opt/RegKnots/data/raw/uscg_bulletins/ingest_stats.json")
REJECTED_LOG = Path("/opt/RegKnots/data/raw/uscg_bulletins/rejected.log")


async def main():
    stats = json.loads(STATS_PATH.read_text()) if STATS_PATH.exists() else {}

    print("=== Ingest stats (from adapter) ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")

    print()
    print("=== DB state ===")
    dsn = api_settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        n = await pool.fetchval("SELECT COUNT(*) FROM regulations WHERE source='uscg_bulletin'")
        print(f"  total chunks: {n}")
        n_docs = await pool.fetchval(
            "SELECT COUNT(DISTINCT section_number) FROM regulations WHERE source='uscg_bulletin'"
        )
        print(f"  distinct bulletins: {n_docs}")
        n_sup = await pool.fetchval(
            "SELECT COUNT(DISTINCT section_number) FROM regulations "
            "WHERE source='uscg_bulletin' AND superseded_by IS NOT NULL"
        )
        print(f"  with superseded_by: {n_sup}")
        n_exp = await pool.fetchval(
            "SELECT COUNT(DISTINCT section_number) FROM regulations "
            "WHERE source='uscg_bulletin' AND expires_date IS NOT NULL"
        )
        print(f"  with expires_date: {n_exp}")

        print()
        print("  Breakdown by publish year:")
        rows = await pool.fetch(
            "SELECT EXTRACT(YEAR FROM published_date)::int AS yr, COUNT(DISTINCT section_number) AS n "
            "FROM regulations WHERE source='uscg_bulletin' AND published_date IS NOT NULL "
            "GROUP BY yr ORDER BY yr"
        )
        for r in rows:
            print(f"    {r['yr']}: {r['n']}")

        print()
        print("  First 20 accepted bulletins (section_number | published | subject preview):")
        rows = await pool.fetch(
            "SELECT section_number, section_title, published_date "
            "FROM regulations WHERE source='uscg_bulletin' AND chunk_index=0 "
            "ORDER BY section_number LIMIT 20"
        )
        for r in rows:
            sn = r["section_number"][:40]
            pd = r["published_date"].isoformat() if r["published_date"] else "-"
            st = r["section_title"][:100].replace("\n", " ")
            print(f"    {sn:<42} {pd}  {st}")

        print()
        print("  Breakdown by canonical-ID prefix:")
        rows = await pool.fetch(
            "SELECT section_number FROM regulations "
            "WHERE source='uscg_bulletin' AND chunk_index=0"
        )
        prefixes = Counter()
        for r in rows:
            sn = r["section_number"]
            if sn.startswith("MSIB"):
                prefixes["MSIB"] += 1
            elif sn.startswith("ALCOAST"):
                prefixes["ALCOAST"] += 1
            elif sn.startswith("NVIC"):
                prefixes["NVIC_mention"] += 1
            elif "PL" in sn[:10]:
                prefixes["CG policy letter"] += 1
            elif sn.startswith("NMC Announcement"):
                prefixes["NMC Announcement"] += 1
            else:
                prefixes["other"] += 1
        for k, v in prefixes.most_common():
            print(f"    {k}: {v}")
    finally:
        await pool.close()

    print()
    print("=== First 20 rejected bulletins (for FN review) ===")
    if REJECTED_LOG.exists():
        lines = REJECTED_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
        # Skip header
        shown = 0
        for line in lines[1:]:
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) < 4:
                continue
            gd_id, reason, subject, preview = parts[0], parts[1], parts[2][:100], parts[3][:80]
            print(f"  [{gd_id}] reason={reason} subject='{subject}' body='{preview}'")
            shown += 1
            if shown >= 20:
                break


if __name__ == "__main__":
    asyncio.run(main())

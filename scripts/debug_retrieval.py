"""Debug a retrieval run end-to-end — see what chunks surfaced for a query.

Usage:
    cd /opt/RegKnots/apps/api
    uv run python /tmp/debug_retrieval.py \
        --query "regulations for SCBA packs for dry cargo/container ships over 70,000 gt" \
        --vessel-type "Containership" --route "international"
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import asyncpg

sys.path.insert(0, "/opt/RegKnots/packages/rag")
sys.path.insert(0, "/opt/RegKnots/apps/api")

from rag.retriever import retrieve
from app.config import settings


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--query", required=True)
    p.add_argument("--vessel-type", default=None)
    p.add_argument("--route", default=None)
    p.add_argument("--cargo", default=None)
    p.add_argument("--limit", type=int, default=12)
    args = p.parse_args()

    vessel_profile = None
    if args.vessel_type or args.route or args.cargo:
        vessel_profile = {
            "vessel_type": args.vessel_type,
            "route_type": args.route,
            "cargo_types": [args.cargo] if args.cargo else [],
        }

    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        hits = await retrieve(
            args.query, pool, settings.openai_api_key,
            vessel_profile=vessel_profile, limit=args.limit,
        )
        print(f"\nQUERY: {args.query!r}")
        if vessel_profile:
            print(f"VESSEL: {vessel_profile}")
        print(f"\n{len(hits)} candidates:")
        for i, h in enumerate(hits, 1):
            src = h["source"]
            sn = h.get("section_number", "?")
            score = h.get("_score", h.get("similarity", 0))
            title = (h.get("section_title") or "").replace("\n", " ")[:80]
            preview = (h.get("full_text") or "").replace("\n", " ")[:120]
            print(f"  {i:2}. [{src:<18}] {sn:<30} score={score:.3f}")
            print(f"      title:   {title}")
            print(f"      preview: {preview}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

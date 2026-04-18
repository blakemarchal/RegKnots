"""Smoke test: retrieval for USCG bulletin queries after Sprint B ingest."""
import asyncio
import sys

import asyncpg

sys.path.insert(0, "/opt/RegKnots/packages/rag")
sys.path.insert(0, "/opt/RegKnots/apps/api")

from rag.retriever import retrieve
from app.config import settings as api_settings

QUERIES = [
    "What recent MSIBs have been issued about fire safety equipment?",
    "Are there any active port security zones I should know about?",
    "What's the latest guidance on mariner medical certificate processing?",
    "Has the Coast Guard issued any enforcement priorities for tanker operations?",
]


async def main():
    dsn = api_settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        for q in QUERIES:
            print(f"\n=== Q: {q}")
            hits = await retrieve(q, pool, api_settings.openai_api_key, limit=5)
            for i, h in enumerate(hits, 1):
                src = h["source"]
                sn = h.get("section_number", "?")
                score = h.get("_score", h.get("similarity", 0))
                marker = "★" if src == "uscg_bulletin" else " "
                print(f" {marker} {i}. [{src}] {sn} | score={score:.3f}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Smoke test: NMC retrieval after nmc_policy + nmc_checklist ingest."""
import asyncio
import sys

import asyncpg

sys.path.insert(0, "/opt/RegKnots/packages/rag")
sys.path.insert(0, "/opt/RegKnots/apps/api")

from rag.retriever import retrieve
from app.config import settings as api_settings

QUERIES = [
    "What's required for my MMC renewal application?",
    "Can I use my Navy sea service to qualify for an MMC?",
    "What's the liftboat policy for credential endorsements?",
    "What are the medical requirements for an MMC?",
]


async def main():
    dsn = api_settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        for q in QUERIES:
            print(f"\n=== Q: {q}")
            hits = await retrieve(q, pool, api_settings.openai_api_key, limit=8)
            for i, h in enumerate(hits, 1):
                src = h["source"]
                sn = h.get("section_number", "?")
                score = h.get("_score", h.get("similarity", 0))
                marker = "★" if src in ("nmc_policy", "nmc_checklist") else " "
                marker_nvic = "▲" if src == "nvic" else marker
                print(f" {marker_nvic} {i}. [{src}] {sn} | score={score:.3f}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

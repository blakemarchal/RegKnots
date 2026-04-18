"""Smoke test: verify NVIC 04-08 content surfaces for medical-cert queries."""
import asyncio
import sys

import asyncpg

sys.path.insert(0, "/opt/RegKnots/packages/rag")
sys.path.insert(0, "/opt/RegKnots/apps/api")

from rag.retriever import retrieve
from app.config import settings as api_settings


async def main():
    dsn = api_settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        for q in [
            "What are the medical standards for an MMC renewal?",
            "Can a mariner with diabetes get an MMC?",
            "hearing aid standards for merchant mariner",
        ]:
            print(f"\nQ: {q}")
            hits = await retrieve(q, pool, api_settings.openai_api_key, limit=8)
            for i, h in enumerate(hits, 1):
                src = h["source"]
                sn = h.get("section_number", "?")
                score = h.get("_score", h.get("similarity", 0))
                print(f"  {i}. [{src}] {sn} | score={score:.3f}")
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

"""Time retrieve_enhanced's phases for one question (2026-10-17): rewrite, the four
searches, rerank. Haiku rewrite + rerank only (~$0.002), no Opus.

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/retrieval_phases.py "question" [towing|container|none]
"""
import asyncio
import logging
import sys
import time

sys.path.insert(0, "/opt/RegKnots/apps/api")
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from app.config import settings  # noqa: E402
from rag.retriever import retrieve_enhanced  # noqa: E402

PROFILES = {
    "towing": {"vessel_name": "check", "vessel_type": "Towing / Tugboat", "flag_state": "United States"},
    "container": {"vessel_name": "check", "vessel_type": "Containership", "flag_state": "United States"},
    "none": None,
}
T0 = time.perf_counter()


class _Stamp(logging.Handler):
    def emit(self, record):
        msg = record.getMessage()
        if any(k in msg for k in ("reformulations for", "Retrieval:", "reranker:", "HTTP Request")):
            print(f"  {time.perf_counter() - T0:5.2f}s  {msg[:150]}", flush=True)


async def main(question: str, profile_key: str) -> None:
    global T0
    for name in ("rag.retriever", "rag.query_rewrite", "rag.reranker", "httpx", "httpx2"):
        lg = logging.getLogger(name)
        lg.setLevel(logging.INFO)
        lg.addHandler(_Stamp())
        lg.propagate = False
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    for run in (1, 2):
        T0 = time.perf_counter()
        print(f"run {run}:")
        await retrieve_enhanced(
            query=question, pool=pool, openai_api_key=settings.openai_api_key, anthropic_client=client,
            vessel_profile=PROFILES[profile_key], limit=8,
            query_rewrite_enabled=settings.query_rewrite_enabled, reranker_enabled=settings.reranker_enabled,
            hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled, hybrid_rrf_k=settings.hybrid_rrf_k,
            jurisdiction_focus="us",
        )
        print(f"  {time.perf_counter() - T0:5.2f}s  retrieve_enhanced done")
    await client.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "towing"))

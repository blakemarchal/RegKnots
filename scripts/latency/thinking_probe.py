"""Which thinking settings Opus 5.5 and Haiku 5.5 accept, and what they do to latency
(2026-10-17). Spends Claude credit (~$0.5): captures one question's real requests through
the engine, replays the answer request to its first word under each accepted setting
(twice), and the rerank / rewrite requests to completion.

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/thinking_probe.py
"""
import asyncio
import copy
import statistics
import sys
from uuid import uuid4

sys.path.insert(0, "/opt/RegKnots/scripts/latency")
sys.path.insert(0, "/tmp")
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from ttft_probe import PROFILES, capture, first_word, time_sidecar  # noqa: E402
from app.config import settings  # noqa: E402
import rag.llm as L  # noqa: E402

OPUS_VARIANTS = {
    "effort_low (now)": {"output_config": {"effort": "low"}},
    "effort_minimal": {"output_config": {"effort": "minimal"}},
    "effort_none": {"output_config": {"effort": "none"}},
    "thinking_disabled": {"thinking": {"type": "disabled"}},
    "budget_1024": {"thinking": {"type": "enabled", "budget_tokens": 1024}},
}
HAIKU_VARIANTS = {
    "effort_low (now)": {"output_config": {"effort": "low"}},
    "effort_minimal": {"output_config": {"effort": "minimal"}},
    "effort_none": {"output_config": {"effort": "none"}},
    "thinking_disabled": {"thinking": {"type": "disabled"}},
}


def with_variant(kw: dict, extra: dict) -> dict:
    kw = copy.deepcopy(kw)
    kw.pop("output_config", None)
    kw.pop("thinking", None)
    kw.update(copy.deepcopy(extra))
    return kw


async def sidecar(client, kw):
    import time
    t = time.perf_counter()
    try:
        res = await L.create_json(client, **kw)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:140]}"}
    return {"s": round(time.perf_counter() - t, 2), "ok": res.data is not None,
            "out": getattr(getattr(res, "usage", None), "output_tokens", None)}


async def main():
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_id = await pool.fetchval("SELECT id FROM users WHERE email = 'blakemarchal@gmail.com'")
    conv_id = uuid4()
    await pool.execute("INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, $3)",
                       conv_id, user_id, "[thinking probe 2026-10-17]")
    try:
        seen = await capture(client, pool, "What records does a Subchapter M towboat have to keep?",
                             PROFILES["towing"], user_id, conv_id)
        answer = seen["answer"]
        print("== Opus answer request, first word (two runs each)")
        for name, extra in OPUS_VARIANTS.items():
            runs = [await first_word(client, with_variant(answer, extra)) for _ in range(2)]
            errs = [r["error"] for r in runs if "error" in r]
            if errs:
                print(f"  {name:20} rejected: {errs[0][:150]}")
            else:
                print(f"  {name:20} first word {[r['ttft'] for r in runs]}  thinking from {[r['think_start'] for r in runs]}")
        for label in ("reranker", "query_rewrite", "coverage check"):
            kw = seen["sidecar"].get(label)
            if not kw:
                continue
            print(f"== Haiku {label} (two runs each)")
            for name, extra in HAIKU_VARIANTS.items():
                runs = [await sidecar(client, with_variant(kw, extra)) for _ in range(2)]
                errs = [r["error"] for r in runs if "error" in r]
                if errs:
                    print(f"  {name:20} rejected: {errs[0][:150]}")
                else:
                    print(f"  {name:20} {[r['s'] for r in runs]} s  json ok {[r['ok'] for r in runs]}")
    finally:
        refs = await pool.fetch("SELECT table_name FROM information_schema.columns WHERE column_name = 'conversation_id' "
                                "AND table_schema = 'public' AND table_name <> 'conversations'")
        for r in refs:
            await pool.execute(f'DELETE FROM "{r["table_name"]}" WHERE conversation_id = $1', conv_id)
        await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
        await client.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

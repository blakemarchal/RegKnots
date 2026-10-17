"""Opus 5.5 fast mode vs standard on captured production answer requests (2026-10-17).
Spends Claude credit (~$1.2 for three questions: full answers at standard and fast price).

Fast mode (`speed: "fast"`, GA for claude-opus-5-5; $8/$40 per MTok, twice standard) runs
the same model at up to 2.5x output tokens per second. Opus 5.5 thinks before its first
text token, and thinking is output, so the first word should come sooner as well.

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/fast_mode_probe.py
"""
import asyncio
import statistics
import sys
import time
from uuid import uuid4

sys.path.insert(0, "/opt/RegKnots/scripts/latency")
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from ttft_probe import PROFILES, capture  # noqa: E402
from app.config import settings  # noqa: E402

QUESTIONS = [
    ("What records does a Subchapter M towboat have to keep?", "towing"),
    ("How many portable fire extinguishers does a 120-foot towing vessel need?", "towing"),
    ("How often do the lifeboats on a containership have to be launched with their crews?", "container"),
]


async def full_answer(client, kw: dict, fast: bool) -> dict:
    kw = dict(kw)
    if fast:
        kw["extra_body"] = {"speed": "fast"}
    t0 = time.perf_counter()
    first = None
    chars = 0
    try:
        async with client.messages.stream(**kw) as s:
            async for ev in s:
                if (ev.type == "content_block_delta" and getattr(ev.delta, "type", "") == "text_delta"):
                    if first is None:
                        first = time.perf_counter() - t0
                    chars += len(ev.delta.text)
            msg = await s.get_final_message()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {str(exc)[:200]}"}
    u = msg.usage
    return {"first": round(first, 2) if first else None, "total": round(time.perf_counter() - t0, 2),
            "out": u.output_tokens, "chars": chars, "speed": getattr(u, "speed", None) or
            (getattr(u, "model_extra", None) or {}).get("speed")}


async def main():
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_id = await pool.fetchval("SELECT id FROM users WHERE email = 'blakemarchal@gmail.com'")
    conv_id = uuid4()
    await pool.execute("INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, $3)",
                       conv_id, user_id, "[fast mode probe 2026-10-17]")
    res = {"standard": [], "fast": []}
    try:
        for question, pk in QUESTIONS:
            kw = (await capture(client, pool, question, PROFILES[pk], user_id, conv_id))["answer"]
            for mode in ("standard", "fast"):
                r = await full_answer(client, kw, fast=(mode == "fast"))
                print(f"{question[:55]:55} {mode:8} {r}", flush=True)
                if r.get("first"):
                    res[mode].append(r)
    finally:
        refs = await pool.fetch("SELECT table_name FROM information_schema.columns WHERE column_name = 'conversation_id' "
                                "AND table_schema = 'public' AND table_name <> 'conversations'")
        for r in refs:
            await pool.execute(f'DELETE FROM "{r["table_name"]}" WHERE conversation_id = $1', conv_id)
        await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
        await client.close()
        await pool.close()
    for mode, rs in res.items():
        if rs:
            print(f"{mode:8} first word median {statistics.median(r['first'] for r in rs):.2f} s, "
                  f"finished median {statistics.median(r['total'] for r in rs):.2f} s, "
                  f"output tokens/s median {statistics.median(r['out'] / max(r['total'] - r['first'], 0.1) for r in rs):.0f}")


if __name__ == "__main__":
    asyncio.run(main())

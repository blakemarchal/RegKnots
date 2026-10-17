"""First-word time of the answer call under candidate settings (2026-10-17). Spends
Claude credit (~$0.5); measures speed only, not quality.

For each question, captures the production answer request twice through the engine:
with the whole-section budget as shipped (rag.sections.CONTEXT_TOKENS) and with a
smaller one. Replays to the first word: Opus 5.5 low (as shipped), Opus with the smaller
budget, Sonnet 5.5 low, Sonnet 5.5 with thinking off ("between_tools").

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/answer_model_probe.py [small_budget]
"""
import asyncio
import copy
import statistics
import sys
from uuid import uuid4

sys.path.insert(0, "/opt/RegKnots/scripts/latency")
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

import rag.sections as S  # noqa: E402
from ttft_probe import PROFILES, capture, first_word  # noqa: E402
from app.config import settings  # noqa: E402

QUESTIONS = [
    ("What records does a Subchapter M towboat have to keep?", "towing"),
    ("How many portable fire extinguishers does a 120-foot towing vessel need?", "towing"),
    ("How often do the lifeboats on a containership have to be launched with their crews?", "container"),
]
SONNET = "claude-sonnet-5-5"


def as_model(kw: dict, model: str, thinking_off: bool = False) -> dict:
    kw = copy.deepcopy(kw)
    kw["model"] = model
    kw["max_tokens"] = 8192
    kw.pop("output_config", None)
    kw.pop("thinking", None)
    if thinking_off:
        kw["thinking"] = {"type": "between_tools"}
    else:
        kw["output_config"] = {"effort": "low"}
    return kw


async def main(small_budget: int):
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    user_id = await pool.fetchval("SELECT id FROM users WHERE email = 'blakemarchal@gmail.com'")
    conv_id = uuid4()
    await pool.execute("INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, $3)",
                       conv_id, user_id, "[answer model probe 2026-10-17]")
    res: dict[str, list] = {"opus_low": [], "opus_low_small_ctx": [], "sonnet_low": [], "sonnet_off": []}
    shipped = S.CONTEXT_TOKENS
    try:
        for question, pk in QUESTIONS:
            full = (await capture(client, pool, question, PROFILES[pk], user_id, conv_id))["answer"]
            S.CONTEXT_TOKENS = small_budget
            try:
                small = (await capture(client, pool, question, PROFILES[pk], user_id, conv_id))["answer"]
            finally:
                S.CONTEXT_TOKENS = shipped
            sizes = (len(str(full["messages"][-1]["content"])), len(str(small["messages"][-1]["content"])))
            row = {
                "opus_low": await first_word(client, full),
                "opus_low_small_ctx": await first_word(client, small),
                "sonnet_low": await first_word(client, as_model(full, SONNET)),
                "sonnet_off": await first_word(client, as_model(full, SONNET, thinking_off=True)),
            }
            print(f"{question[:60]} | user turn {sizes[0]} vs {sizes[1]} chars", flush=True)
            for k, v in row.items():
                print(f"    {k:20} {v.get('ttft')} s{'  ' + v['error'][:120] if 'error' in v else ''}", flush=True)
                if v.get("ttft"):
                    res[k].append(v["ttft"])
    finally:
        refs = await pool.fetch("SELECT table_name FROM information_schema.columns WHERE column_name = 'conversation_id' "
                                "AND table_schema = 'public' AND table_name <> 'conversations'")
        for r in refs:
            await pool.execute(f'DELETE FROM "{r["table_name"]}" WHERE conversation_id = $1', conv_id)
        await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
        await client.close()
        await pool.close()
    print("\nmedian first word:", {k: round(statistics.median(v), 2) for k, v in res.items() if v})


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 12000))

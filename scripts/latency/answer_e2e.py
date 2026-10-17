"""One real answer through the production engine, timed (2026-10-17). Spends Claude credit.

Runs chat_with_progress in-process on the VPS with the flags the chat route
passes, on a throwaway conversation in Blake's account (deleted afterwards with
every row that references it), and prints when the first word and the finished
answer arrived plus the engine's own "answer timing" line. Each question costs
about $0.10-0.15 (Opus answer, Haiku sidecars, web research when it runs).

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/answer_e2e.py [towing|container|none] "question" ["question" ...]

2026-10-17 (later) — the process is warmed first like the API (source caches,
side-table check, keyword caches, OpenAI connection: one retrieval of an unrelated
question, Haiku only), so the timings are a running API's, not a cold start's.
"""
import asyncio
import logging
import sys
import time
from uuid import uuid4

sys.path.insert(0, "/opt/RegKnots/apps/api")
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

from app.config import settings  # noqa: E402
from rag.engine import chat_with_progress  # noqa: E402
from rag.retriever import retrieve_enhanced  # noqa: E402

PROFILES = {
    "towing": {"vessel_name": "E2E check", "vessel_type": "Towing / Tugboat", "flag_state": "United States"},
    "container": {"vessel_name": "E2E check", "vessel_type": "Containership", "flag_state": "United States"},
    "none": None,
}


class _Grab(logging.Handler):
    def __init__(self):
        super().__init__()
        self.lines: list[str] = []

    def emit(self, record):
        msg = record.getMessage()
        if msg.startswith(("answer timing:", "coverage:", "web research:", "speculative answer")):
            self.lines.append(msg)


async def main(questions: list[str], profile_key: str) -> None:
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    t = time.perf_counter()
    await retrieve_enhanced(
        query="how often must the emergency fire pump be tested", pool=pool,
        openai_api_key=settings.openai_api_key, anthropic_client=client, vessel_profile=PROFILES[profile_key],
        limit=8, query_rewrite_enabled=True, reranker_enabled=True, jurisdiction_focus="us",
    )
    print(f"warm-up retrieval {time.perf_counter() - t:.1f}s")
    for question in questions:
        print(f"=== {question}")
        await one(question, profile_key, pool, client)
    await client.close()
    await pool.close()


async def one(question: str, profile_key: str, pool, client) -> None:
    grab = _Grab()
    logging.getLogger("rag.engine").addHandler(grab)
    logging.getLogger("rag.engine").setLevel(logging.INFO)
    user_id = await pool.fetchval("SELECT id FROM users WHERE email = 'blakemarchal@gmail.com'")
    conv_id = uuid4()
    await pool.execute("INSERT INTO conversations (id, user_id, title) VALUES ($1, $2, $3)",
                       conv_id, user_id, "[latency check 2026-10-17]")
    t0 = time.perf_counter()
    first = None
    answer = []
    try:
        async for ev in chat_with_progress(
            query=question, conversation_history=[], vessel_profile=PROFILES[profile_key], pool=pool,
            anthropic_client=client, openai_api_key=settings.openai_api_key, conversation_id=conv_id,
            user_id=user_id, subscription_tier="captain", user_jurisdiction_focus="us",
            xai_api_key=settings.xai_api_key,
            web_fallback_enabled=settings.web_fallback_enabled,
            web_fallback_cosine_threshold=settings.web_fallback_cosine_threshold,
            web_fallback_daily_cap=settings.web_fallback_daily_cap,
            web_fallback_cascade_enabled=settings.web_fallback_cascade_enabled,
            hedge_judge_enabled=settings.hedge_judge_enabled,
            query_rewrite_enabled=settings.query_rewrite_enabled,
            reranker_enabled=settings.reranker_enabled,
            citation_oracle_enabled=settings.citation_oracle_enabled,
            hybrid_retrieval_enabled=settings.hybrid_retrieval_enabled,
            hybrid_rrf_k=settings.hybrid_rrf_k,
            confidence_tiers_mode=settings.confidence_tiers_mode,
            judge_on_cited_enabled=settings.judge_on_cited_enabled,
            lead_with_answer_enabled=settings.lead_with_answer_enabled,
            model_led_grounding_enabled=settings.model_led_grounding_enabled,
            whole_sections_enabled=settings.whole_sections_enabled,
            provenance_prompt_enabled=settings.provenance_prompt_enabled,
            imo_dates_prompt_enabled=settings.imo_dates_prompt_enabled,
            pipeline_v2_enabled=settings.answer_pipeline_v2_enabled,
            web_research_daily_cap=settings.web_research_daily_cap,
            web_research_monthly_cap=settings.web_research_monthly_cap,
            speculative_answer_enabled=settings.speculative_answer_enabled,
            synthesis_model_floor=settings.synthesis_model_floor or None,
        ):
            if ev["event"] == "delta":
                if first is None:
                    first = time.perf_counter() - t0
                answer.append(ev["data"])
            elif ev["event"] == "status":
                print(f"  {time.perf_counter() - t0:5.1f}s  status: {ev['data']}", flush=True)
            elif ev["event"] == "done":
                d = ev["data"]
                print(f"  {time.perf_counter() - t0:5.1f}s  done: model {d.get('model_used')}, "
                      f"{len(d.get('cited_regulations') or [])} citations, "
                      f"{len(d.get('web_sources') or [])} web sources, {len(''.join(answer))} chars")
        print(f"first word {first:.1f}s, total {time.perf_counter() - t0:.1f}s")
        await asyncio.sleep(8)          # background judge / gap log finish before cleanup
    finally:
        refs = await pool.fetch(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE column_name = 'conversation_id' AND table_schema = 'public' AND table_name <> 'conversations'")
        for r in refs:
            await pool.execute(f'DELETE FROM "{r["table_name"]}" WHERE "{r["column_name"]}" = $1', conv_id)
        await pool.execute("DELETE FROM conversations WHERE id = $1", conv_id)
        logging.getLogger("rag.engine").removeHandler(grab)
    for line in grab.lines:
        print("  log:", line[:400])
    print("answer starts:", "".join(answer)[:300].replace("\n", " "))


if __name__ == "__main__":
    args = sys.argv[1:]
    key = args.pop(0) if args and args[0] in PROFILES else "towing"
    asyncio.run(main(args, key))

"""How often the original question's search alone already gives the final answer context
(2026-10-17). Haiku only (~$0.10): for each gold pair, runs retrieve_enhanced with the
pipelined rerank, rebuilds the top 8 from the primary search's candidates and scores
alone, and compares both after whole-section expansion. If they match often, an answer
call started on the primary context (and used only when it matches) would save the
reformulation searches and the second scoring.

  cd /opt/RegKnots/apps/api && .venv/bin/python /opt/RegKnots/scripts/latency/primary_context_probe.py [pairs]
"""
import asyncio
import sys

sys.path.insert(0, "/opt/RegKnots/scripts")
import eval_retrieval as ER  # noqa: E402  (paths + the gold set)
import asyncpg  # noqa: E402
from anthropic import AsyncAnthropic  # noqa: E402

import rag.reranker as RR  # noqa: E402
import rag.retriever as R  # noqa: E402
from app.config import settings  # noqa: E402
from rag.context import build_context  # noqa: E402
from rag.sections import CONTEXT_TOKENS, expand_sections  # noqa: E402


async def main(limit_pairs: int):
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=2, max_size=10)
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    orig_score = RR.score_chunks
    same_top = same_ctx = n = 0
    for qid, query, vessel, profile, expected, wrong in list(ER._gold_pairs())[:limit_pairs]:
        first: dict = {}

        async def score(q, chunks, c, per_chunk_chars=RR._PER_CHUNK_TEXT_CHARS):
            res = await orig_score(q, chunks, c, per_chunk_chars)
            if "rows" not in first:
                first.update(rows=list(chunks), scores=res)
            return res

        RR.score_chunks = score
        try:
            final = await R.retrieve_enhanced(
                query=query, pool=pool, openai_api_key=settings.openai_api_key, anthropic_client=client,
                vessel_profile=profile, limit=8, query_rewrite_enabled=True, reranker_enabled=True,
                rerank_pool_size=30, jurisdiction_focus="us",
            )
        finally:
            RR.score_chunks = orig_score
        if not first.get("scores"):
            continue
        prim = R._merge_chunks(first["rows"], [])
        R._apply_title_boost(prim, R._extract_keywords(query))
        prim.sort(key=lambda x: float(x.get("similarity", 0.0)), reverse=True)
        by_id = {first["rows"][i]["id"]: s for i, s in first["scores"].items() if 0 <= i < len(first["rows"])}
        prim = RR.apply_scores(prim, {i: by_id.get(c["id"], 0) for i, c in enumerate(prim)}, top_k=8)[:8]
        n += 1
        top_match = [c["id"] for c in prim] == [c["id"] for c in final]
        ctx_a, _ = build_context(await expand_sections(pool, prim, query), max_tokens=CONTEXT_TOKENS)
        ctx_b, _ = build_context(await expand_sections(pool, final, query), max_tokens=CONTEXT_TOKENS)
        same_top += top_match
        same_ctx += ctx_a == ctx_b
        print(f"  {qid:8} {vessel}: same top-8 {top_match}, same context {ctx_a == ctx_b}", flush=True)
    print(f"\n{n} pairs: same top-8 {same_top}, same context {same_ctx}")
    await client.close()
    await pool.close()


if __name__ == "__main__":
    asyncio.run(main(int(sys.argv[1]) if len(sys.argv) > 1 else 40))

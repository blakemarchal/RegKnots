#!/usr/bin/env python3
"""Retrieval-only eval harness — recall@k / MRR over the curated gold set.

2026-07-19 (Fable audit follow-through). The answer-level harness
(eval_rag_baseline.py) grades the SYNTHESIZED answer, so a retrieval miss
rescued by the reranker/web-fallback still grades A — it cannot attribute
quality to the retriever. This harness calls the retrieval layer directly
and grades whether the expected sections landed in the top-k. Use it to
A/B candidate-generation changes (dense vs hybrid RRF, ef_search, boost
magnitudes) BEFORE they ship.

Reuses the curated QUESTIONS x VESSELS gold set from eval_rag_baseline.py
(imported, not copied) — per-vessel expected regexes + known-wrong
subchapter patterns. sailor_speak questions are skipped (no ground truth).

Arms:
  dense        retrieve()                    — today's production candidates
  hybrid       retrieve_hybrid()             — dense + lexical RRF fusion
  dense-prod   retrieve_enhanced(hybrid=F)   — + Haiku rewrite + reranker
  hybrid-prod  retrieve_enhanced(hybrid=T)   — + Haiku rewrite + reranker

Grading per (question, vessel) pair, top-k (default 8):
  STRONG hit — expected regex matches a chunk's section_number/title
               (the actual reg landed).
  WEAK hit   — expected regex matches only full_text (content mentioning
               the reg landed; may still let synthesis answer).
  wrong_sub  — count of top-k chunks whose section_number matches a
               known-wrong pattern (precision proxy).
Metrics: strong-recall@k, weak-recall@k, MRR (strong), wrong-rate, latency.

Run on the VPS (needs live DB + OpenAI key):
  uv run python scripts/eval_retrieval.py --arm dense
  uv run python scripts/eval_retrieval.py --arm hybrid --ef-search 100
  uv run python scripts/eval_retrieval.py --compare data/eval/retrieval/A.json data/eval/retrieval/B.json

Deterministic for dense/hybrid arms (embedding + SQL only; ~$0.01 of
embeddings per run). -prod arms add Haiku rewrite+rerank (~$0.15/run,
mildly nondeterministic) — use them to confirm, not to explore.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(os.environ.get("REGKNOTS_REPO", "/opt/RegKnots"))
sys.path.insert(0, str(_REPO / "packages" / "rag"))
sys.path.insert(0, str(_REPO / "apps" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import asyncpg  # noqa: E402

from app.config import settings  # noqa: E402
from rag.retriever import retrieve, retrieve_enhanced, retrieve_hybrid  # noqa: E402

# Reuse the curated gold set — import, don't copy.
from eval_rag_baseline import QUESTIONS, VESSELS, _expected_for_vessel  # noqa: E402

_OUT_DIR = _REPO / "data" / "eval" / "retrieval"


def _dsn() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def _make_pool(ef_search: int) -> asyncpg.Pool:
    async def _init(conn):
        if ef_search > 0:
            await conn.execute(f"SET hnsw.ef_search = {int(ef_search)}")

    return await asyncpg.create_pool(_dsn(), min_size=2, max_size=6, init=_init)


def _gold_pairs():
    """Yield (qid, query, vessel_code, profile_dict|None, expected, wrong_sub)."""
    for q in QUESTIONS:
        if getattr(q, "sailor_speak", False):
            continue  # no ground truth — can't grade retrieval
        for v in q.vessels:
            expected = _expected_for_vessel(q, v)
            if not expected:
                continue
            profile = None if v == "V0" else VESSELS[v].profile_dict
            yield q.qid, q.query, v, profile, expected, list(q.wrong_sub)


async def _run_pair(arm, pool, anthropic_client, query, profile, limit):
    if arm == "dense":
        return await retrieve(
            query, pool=pool, openai_api_key=settings.openai_api_key,
            vessel_profile=profile, limit=limit,
        )
    if arm == "hybrid":
        return await retrieve_hybrid(
            query, pool=pool, openai_api_key=settings.openai_api_key,
            vessel_profile=profile, limit=limit,
        )
    # production-shaped arms
    return await retrieve_enhanced(
        query=query, pool=pool, openai_api_key=settings.openai_api_key,
        anthropic_client=anthropic_client, vessel_profile=profile, limit=limit,
        query_rewrite_enabled=True, reranker_enabled=True, rerank_pool_size=30,
        hybrid_retrieval_enabled=(arm == "hybrid-prod"), hybrid_rrf_k=60,
    )


def _grade(chunks, expected, wrong_sub, limit):
    exp = [re.compile(p, re.IGNORECASE) for p in expected]
    wrong = [re.compile(p, re.IGNORECASE) for p in wrong_sub]
    strong_rank = weak_rank = None
    wrong_hits = 0
    for i, c in enumerate(chunks[:limit], start=1):
        strong_text = f"{c.get('section_number') or ''} :: {c.get('section_title') or ''}"
        full = c.get("full_text") or ""
        if strong_rank is None and any(p.search(strong_text) for p in exp):
            strong_rank = i
        if weak_rank is None and any(
            p.search(strong_text) or p.search(full) for p in exp
        ):
            weak_rank = i
        if any(p.search(c.get("section_number") or "") for p in wrong):
            wrong_hits += 1
    return strong_rank, weak_rank, wrong_hits


async def run_arm(arm: str, ef_search: int, limit: int, tag: str | None):
    anthropic_client = None
    if arm.endswith("-prod"):
        from anthropic import AsyncAnthropic
        anthropic_client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    pool = await _make_pool(ef_search)
    rows = []
    try:
        for qid, query, vessel, profile, expected, wrong_sub in _gold_pairs():
            t0 = time.perf_counter()
            try:
                chunks = await _run_pair(arm, pool, anthropic_client, query, profile, limit)
            except Exception as exc:  # keep the run alive; a crash is a finding
                rows.append({
                    "qid": qid, "vessel": vessel, "error": f"{type(exc).__name__}: {exc}",
                    "strong_rank": None, "weak_rank": None, "wrong_hits": 0,
                    "latency_ms": round((time.perf_counter() - t0) * 1000),
                })
                continue
            strong, weak, wrong_hits = _grade(chunks, expected, wrong_sub, limit)
            rows.append({
                "qid": qid, "vessel": vessel,
                "strong_rank": strong, "weak_rank": weak, "wrong_hits": wrong_hits,
                "top": [
                    {"source": c.get("source"), "section": c.get("section_number")}
                    for c in chunks[:limit]
                ],
                "latency_ms": round((time.perf_counter() - t0) * 1000),
            })
            sys.stdout.write(".")
            sys.stdout.flush()
    finally:
        await pool.close()
        if anthropic_client is not None:
            await anthropic_client.close()
    print()

    graded = [r for r in rows if "error" not in r]
    n = len(graded)
    strong_hits = sum(1 for r in graded if r["strong_rank"])
    weak_hits = sum(1 for r in graded if r["weak_rank"])
    mrr = sum(1.0 / r["strong_rank"] for r in graded if r["strong_rank"]) / n if n else 0
    wrong_pairs = sum(1 for r in graded if r["wrong_hits"] > 0)
    lat = [r["latency_ms"] for r in graded]

    summary = {
        "arm": arm, "ef_search": ef_search, "limit": limit,
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "pairs": n, "errors": len(rows) - n,
        "strong_recall_at_k": round(strong_hits / n, 4) if n else 0,
        "weak_recall_at_k": round(weak_hits / n, 4) if n else 0,
        "mrr_strong": round(mrr, 4),
        "pairs_with_wrong_sub": wrong_pairs,
        "latency_ms_p50": statistics.median(lat) if lat else 0,
        "latency_ms_p95": (sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else 0),
    }

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}-{arm}-ef{ef_search}" + (f"-{tag}" if tag else "")
    out = _OUT_DIR / f"{name}.json"
    out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1), encoding="utf-8")

    print(json.dumps(summary, indent=2))
    print(f"wrote {out}")
    return out


def compare(path_a: str, path_b: str):
    a = json.loads(Path(path_a).read_text(encoding="utf-8"))
    b = json.loads(Path(path_b).read_text(encoding="utf-8"))
    ra = {(r["qid"], r["vessel"]): r for r in a["rows"] if "error" not in r}
    rb = {(r["qid"], r["vessel"]): r for r in b["rows"] if "error" not in r}
    both = sorted(set(ra) & set(rb))
    a_arm, b_arm = a["summary"]["arm"], b["summary"]["arm"]

    print(f"\n== {a_arm} (A) vs {b_arm} (B) — {len(both)} shared pairs ==")
    for k in ("strong_recall_at_k", "weak_recall_at_k", "mrr_strong",
              "pairs_with_wrong_sub", "latency_ms_p50"):
        print(f"  {k:24s} A={a['summary'][k]!s:>8}  B={b['summary'][k]!s:>8}")

    gained = [k for k in both if not ra[k]["strong_rank"] and rb[k]["strong_rank"]]
    lost = [k for k in both if ra[k]["strong_rank"] and not rb[k]["strong_rank"]]
    print(f"\n  B GAINS strong hit on {len(gained)}: {gained}")
    print(f"  B LOSES strong hit on {len(lost)}: {lost}")
    for k in lost:
        print(f"\n  -- LOST {k}: A rank={ra[k]['strong_rank']} | B top sections:")
        for t in rb[k].get("top", [])[:8]:
            print(f"       [{t['source']}] {t['section']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["dense", "hybrid", "dense-prod", "hybrid-prod"])
    ap.add_argument("--ef-search", type=int, default=0, help="0 = pgvector default (40)")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument("--tag", default=None)
    ap.add_argument("--compare", nargs=2, metavar=("A.json", "B.json"))
    args = ap.parse_args()

    if args.compare:
        compare(*args.compare)
        return
    if not args.arm:
        ap.error("--arm required (or --compare)")
    asyncio.run(run_arm(args.arm, args.ef_search, args.limit, args.tag))


if __name__ == "__main__":
    main()

"""Sprint D6.84 — Confidence tier router gold-set evaluation harness.

Reads data/eval/tier_router_gold.json and runs each query against the
chat() pipeline with CONFIDENCE_TIERS_MODE=shadow (or live). Compares
the router's tier decision against the expected tier and writes a
results.jsonl + console summary.

⚠ This script makes real Anthropic / OpenAI API calls and writes to
the production-shaped DB. NEVER run it without intent. The standard
flow is:

    1. Wait until shadow mode has accumulated ~24h of natural traffic
       (or run this harness once on dev with ANTHROPIC_API_KEY set).
    2. Review results manually (Karynn + Blake).
    3. Iterate the classifier prompt + thresholds based on misroutes.
    4. Re-run.
    5. Once stable, propose CONFIDENCE_TIERS_MODE=live to the user.

Usage:
    uv run python scripts/eval_tier_router.py [--limit N] [--qid X]

Environment:
    ANTHROPIC_API_KEY, OPENAI_API_KEY, REGKNOTS_DATABASE_URL
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "rag"))
sys.path.insert(0, str(REPO_ROOT / "apps" / "api"))

import asyncpg
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv(REPO_ROOT / ".env", override=True)


def _load_gold() -> dict:
    p = REPO_ROOT / "data" / "eval" / "tier_router_gold.json"
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def _matches(expected, actual_tier: int) -> bool:
    """Soft match — '1_or_3' means tier 1 or 3 both pass."""
    if isinstance(expected, int):
        return expected == actual_tier
    if isinstance(expected, str) and "_or_" in expected:
        choices = {int(p) for p in expected.split("_or_")}
        return actual_tier in choices
    return False


async def _run(args: argparse.Namespace) -> None:
    from rag.engine import chat
    from rag.models import ChatMessage

    anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    database_url = os.environ.get("REGKNOTS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit("REGKNOTS_DATABASE_URL or DATABASE_URL required")
    pool = await asyncpg.create_pool(database_url, min_size=1, max_size=4)

    gold = _load_gold()
    queries = gold["queries"]
    if args.qid:
        queries = [q for q in queries if q["qid"] == args.qid]
    if args.limit:
        queries = queries[: args.limit]

    out_dir = REPO_ROOT / "data" / "eval" / f"tier_router_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "results.jsonl"

    print(f"Running {len(queries)} queries against the live chat pipeline.")
    print(f"Mode: shadow (set CONFIDENCE_TIERS_MODE=shadow on the API to see rows in tier_router_shadow_log).")
    print(f"Output: {results_path}\n")

    pass_count = 0
    fail_count = 0
    rows = []
    for q in queries:
        qid = q["qid"]
        query = q["query"]
        expected = q["expected_tier"]

        try:
            response = await chat(
                query=query,
                conversation_history=[],
                vessel_profile=None,
                pool=pool,
                anthropic_client=anthropic_client,
                openai_api_key=openai_api_key,
                conversation_id=uuid.uuid4(),
                confidence_tiers_mode="live",  # render-and-log so we get a TierMetadata back
            )
            actual_tier = response.tier_metadata.tier if response.tier_metadata else None
            actual_label = response.tier_metadata.label if response.tier_metadata else None
            ok = _matches(expected, actual_tier) if actual_tier is not None else False

            row = {
                "qid": qid,
                "query": query,
                "expected_tier": expected,
                "actual_tier": actual_tier,
                "actual_label": actual_label,
                "pass": ok,
                "answer_preview": response.answer[:300],
                "verified_citations": len(response.cited_regulations),
                "web_fallback": response.web_fallback.confidence if response.web_fallback else None,
            }
            rows.append(row)
            if ok:
                pass_count += 1
                print(f"  PASS  [{qid}] expected={expected} actual={actual_tier} ({actual_label})")
            else:
                fail_count += 1
                print(f"  FAIL  [{qid}] expected={expected} actual={actual_tier} ({actual_label}) — {query[:60]!r}")
        except Exception as exc:
            fail_count += 1
            print(f"  ERROR [{qid}] {type(exc).__name__}: {str(exc)[:200]}")
            rows.append({"qid": qid, "query": query, "expected_tier": expected, "error": f"{type(exc).__name__}: {exc}"})

    with results_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    print(f"\n──────")
    print(f"PASS: {pass_count}   FAIL: {fail_count}   TOTAL: {len(rows)}")
    if pass_count + fail_count > 0:
        print(f"Pass rate: {100.0 * pass_count / (pass_count + fail_count):.1f}%")
    print(f"Results: {results_path}")

    await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Run at most N queries (smoke).")
    parser.add_argument("--qid", type=str, default=None, help="Run only the matching qid (e.g. JORDAN-1).")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()

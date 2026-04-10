"""
Diagnostic for hybrid (vector + keyword) retrieval.

Tests that identifier-based queries activate keyword search and produce
correct results, while queries without identifiers stay pure-vector.

Usage:
    uv run python test_hybrid_search.py
"""

import asyncio
import logging
import os
from pathlib import Path

import asyncpg
from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_REPO_ROOT / ".env", override=True)

from rag.retriever import _extract_identifiers, retrieve  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(levelname)s  %(message)s",
)

# ── Test cases ────────────────────────────────────────────────────────────────

CASES = [
    {
        "query": "What is the emergency response for a UN1219 isopropanol spill?",
        "expect_ids": [{"type": "un_number", "value": "UN1219"}],
        "expect_keyword_active": True,
        "note": "Should find ERG Guide 129 and/or ERG Yellow 1212-1228 via keyword search",
    },
    {
        "query": "What does 46 CFR 35.10-5 require?",
        "expect_ids": [{"type": "cfr_section", "value": "46 CFR 35.10-5"}],
        "expect_keyword_active": True,
        "note": "Should find the relevant CFR chunk via keyword search",
    },
    {
        "query": "Explain COLREGs Rule 14",
        "expect_ids": [{"type": "colregs_rule", "value": "Rule 14"}],
        "expect_keyword_active": True,
        "note": "Should find the Rule 14 head-on situation chunk",
    },
    {
        "query": "What are the SOLAS requirements for fire detection?",
        "expect_ids": [],
        "expect_keyword_active": False,
        "note": "No identifiers — pure vector search, hybrid should NOT activate",
    },
]


def test_identifier_detection():
    """Unit test for _extract_identifiers — no DB needed."""
    print("\n" + "=" * 60)
    print("IDENTIFIER DETECTION (offline)")
    print("=" * 60)

    all_pass = True
    for case in CASES:
        ids = _extract_identifiers(case["query"])
        expected = case["expect_ids"]

        matched = True
        if len(ids) != len(expected):
            matched = False
        else:
            for exp in expected:
                if not any(i["type"] == exp["type"] and i["value"] == exp["value"] for i in ids):
                    matched = False

        status = "PASS" if matched else "FAIL"
        if not matched:
            all_pass = False

        print(f"\n[{status}] {case['query']}")
        print(f"  Expected: {expected}")
        print(f"  Got:      {[{'type': i['type'], 'value': i['value']} for i in ids]}")

    return all_pass


async def test_hybrid_retrieve():
    """Full retrieval test — requires DB + OpenAI key."""
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    database_url = os.environ.get("REGKNOTS_DATABASE_URL", "")

    if not openai_api_key or not database_url:
        print("\nSkipping retrieval test — OPENAI_API_KEY or REGKNOTS_DATABASE_URL not set")
        return True

    pool = await asyncpg.create_pool(database_url)

    print("\n" + "=" * 60)
    print("HYBRID RETRIEVAL (live)")
    print("=" * 60)

    try:
        for case in CASES:
            print(f"\n--- Query: {case['query']}")
            print(f"    Note:  {case['note']}")

            results = await retrieve(
                query=case["query"],
                pool=pool,
                openai_api_key=openai_api_key,
                limit=8,
            )

            if results:
                print(f"    Top {len(results)} results:")
                for i, r in enumerate(results, 1):
                    score = r.get("_score", r.get("similarity", 0))
                    print(
                        f"      {i}. {r.get('source', '?')}/{r.get('section_number', '?')} "
                        f"(score={score:.3f}, sim={float(r.get('similarity', 0)):.3f})"
                    )
            else:
                print("    No results returned")
            print()
    finally:
        await pool.close()

    return True


async def main():
    id_pass = test_identifier_detection()
    await test_hybrid_retrieve()

    if id_pass:
        print("\nAll identifier detection tests passed.")
    else:
        print("\nSome identifier detection tests FAILED.")


if __name__ == "__main__":
    asyncio.run(main())

"""
Diagnostic for hybrid (vector + keyword) retrieval.

Tests identifier detection, broad keyword extraction, and full retrieval
across multiple query types.

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

from rag.retriever import _extract_identifiers, _extract_keywords, retrieve  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(name)s %(levelname)s  %(message)s",
)

# ── Test cases ────────────────────────────────────────────────────────────────

CASES = [
    {
        "query": "What ERG guide covers chlorine gas?",
        "expect_ids": [],
        "expect_keywords_contain": ["chlorine"],
        "note": "No identifier. Keyword 'chlorine' should find ERG Guide 124.",
    },
    {
        "query": "What is the emergency response for a UN1219 isopropanol spill?",
        "expect_ids": [{"type": "un_number", "value": "UN1219"}],
        "expect_keywords_contain": ["isopropanol"],
        "note": "Both identifier (UN1219) and keyword (isopropanol). Guide 129 should appear.",
    },
    {
        "query": "What are the SOLAS requirements for fire detection on cargo ships?",
        "expect_ids": [],
        "expect_keywords_contain": ["fire", "detection"],
        "note": "Keywords supplement vector search. SOLAS Ch.II-2 should still top results.",
    },
    {
        "query": "What are the COLREGs rules for vessels restricted in ability to maneuver?",
        "expect_ids": [],
        "expect_keywords_contain": ["restricted", "maneuver"],
        "note": "Keywords: restricted, ability, maneuver. COLREGs Rules 3/27 expected.",
    },
    {
        "query": "How do I handle an ammonia leak?",
        "expect_ids": [],
        "expect_keywords_contain": ["ammonia", "leak"],
        "note": "No identifier. Keyword 'ammonia' should find ERG Guide 125.",
    },
]


def test_identifier_detection():
    """Unit test for _extract_identifiers -- no DB needed."""
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


def test_keyword_extraction():
    """Unit test for _extract_keywords -- no DB needed."""
    print("\n" + "=" * 60)
    print("KEYWORD EXTRACTION (offline)")
    print("=" * 60)

    all_pass = True
    for case in CASES:
        kws = _extract_keywords(case["query"])
        expected = case["expect_keywords_contain"]

        matched = all(e in kws for e in expected)
        status = "PASS" if matched else "FAIL"
        if not matched:
            all_pass = False

        print(f"\n[{status}] {case['query']}")
        print(f"  Expected to contain: {expected}")
        print(f"  Got: {kws}")

    return all_pass


async def test_hybrid_retrieve():
    """Full retrieval test -- requires DB + OpenAI key."""
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")
    database_url = os.environ.get("REGKNOTS_DATABASE_URL", "")

    if not openai_api_key or not database_url:
        print("\nSkipping retrieval test -- OPENAI_API_KEY or REGKNOTS_DATABASE_URL not set")
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
    kw_pass = test_keyword_extraction()
    await test_hybrid_retrieve()

    if id_pass and kw_pass:
        print("\nAll offline tests passed.")
    else:
        failed = []
        if not id_pass:
            failed.append("identifier detection")
        if not kw_pass:
            failed.append("keyword extraction")
        print(f"\nFAILED: {', '.join(failed)}")


if __name__ == "__main__":
    asyncio.run(main())

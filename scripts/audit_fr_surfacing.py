"""
D6.48 audit — diagnose why French regulations aren't reaching users.

Runs four read-only checks:
  A. DB-level corpus probe — confirm fr_transport chunks exist and are
     retrievable via raw cosine without any jurisdiction filter.
  B. Retrieval-only matrix — 6 queries × 6 profiles, log top-K source
     mix per cell. Reveals where the jurisdiction filter clips valid
     hits, where cross-lingual ranking under-weights foreign content,
     and where persona priors over-weight US/UK content.
  C. Query→jurisdiction-pattern matcher — for each query in B, log what
     allowed_jurisdictions(query, vessel_profile) returns. This is the
     smoking-gun output: if FR queries don't surface 'fr' in the allow
     set, fr_transport is being filtered before ranking.
  D. Replay calibration — fire the web fallback against the last 50
     real hedge queries to populate web_fallback_responses with a soft
     baseline for Phase 2 review.

Usage on prod:
  ssh root@prod 'set -a && source /opt/RegKnots/.env && set +a && \
    cd /opt/RegKnots && \
    /root/.local/bin/uv run --project apps/api python -- \
    scripts/audit_fr_surfacing.py'
"""

import asyncio
import json
import os
import sys
from typing import Any

import asyncpg
from openai import AsyncOpenAI

sys.path.insert(0, "/opt/RegKnots/packages/rag")

from rag.jurisdiction import (
    allowed_jurisdictions,
    jurisdictions_in_query,
    flag_to_jurisdiction,
)


# ── Test grid ────────────────────────────────────────────────────────────────

# Queries chosen to hit each foreign-language source plus a US baseline.
TEST_QUERIES = [
    ("FR-explicit-en",   "What does French maritime law say about ship registration?"),
    ("FR-explicit-fr",   "Quelles sont les exigences d'identification des navires en France?"),
    ("DE-explicit-en",   "What German requirements apply to ISM cyber security?"),
    ("ES-explicit-en",   "What does Spanish DGMM regulation say about vessel inspection?"),
    ("IT-explicit-en",   "What Italian rules apply to bunkering operations?"),
    ("NO-explicit-en",   "What Norwegian NMA rules cover halon phase-out?"),
    ("US-baseline",      "What does 33 CFR say about anchorage?"),
    ("INTL-baseline",    "What does SOLAS chapter II-2 require for fire protection?"),
]

# Vessel profiles to test the filter under.
TEST_PROFILES = [
    ("no-profile",     None),
    ("us-flag",        {"flag_state": "United States", "vessel_type": "tanker"}),
    ("fr-flag",        {"flag_state": "France",        "vessel_type": "container"}),
    ("de-flag",        {"flag_state": "Germany",       "vessel_type": "ro-ro"}),
    ("uk-flag",        {"flag_state": "United Kingdom","vessel_type": "tanker"}),
    ("liberia-flag",   {"flag_state": "Liberia",       "vessel_type": "bulk carrier"}),
]


# ── Step A: DB-level corpus probe ───────────────────────────────────────────

async def step_a_corpus_probe(pool: asyncpg.Pool, openai: AsyncOpenAI) -> None:
    print("=" * 70)
    print("STEP A — DB-level corpus probe (no jurisdiction filter)")
    print("=" * 70)

    # 1. Confirm fr_transport rows exist.
    counts = await pool.fetch(
        "SELECT source, language, COUNT(*) AS chunks "
        "FROM regulations "
        "WHERE source IN ('fr_transport', 'bg_verkehr', 'dgmm_es', "
        "                 'it_capitaneria', 'nma_rsv') "
        "GROUP BY source, language ORDER BY source, language"
    )
    print("\nFlag-state corpus counts:")
    for r in counts:
        print(f"  {r['source']:16s} lang={r['language']:4s} chunks={r['chunks']}")

    # 2. Raw vector search (no filter) for FR-style queries — does FR
    #    content come back in the top-K?
    queries = [
        "ship identification requirements France",
        "exigences identification des navires France",
        "Code des transports articles maritimes",
    ]
    for q in queries:
        emb = await openai.embeddings.create(
            model="text-embedding-3-small", input=q,
        )
        vec = "[" + ",".join(f"{x:.8f}" for x in emb.data[0].embedding) + "]"
        rows = await pool.fetch(
            "SELECT source, language, section_number, "
            "       1 - (embedding <=> $1::vector) AS sim "
            "FROM regulations "
            "ORDER BY embedding <=> $1::vector LIMIT 5",
            vec,
        )
        print(f"\n  Q: {q!r}")
        for r in rows:
            print(f"    {r['sim']:.3f}  [{r['language']:4s}] {r['source']:16s} {r['section_number'][:60]}")


# ── Step B + C: jurisdiction pattern matrix ────────────────────────────────

async def step_b_jurisdiction_matrix(pool: asyncpg.Pool, openai: AsyncOpenAI) -> None:
    print("\n" + "=" * 70)
    print("STEP B + C — query × profile retrieval matrix")
    print("=" * 70)
    print("  cell shows: allow-set | top-3 (lang/source)")
    print()

    for q_label, q_text in TEST_QUERIES:
        print(f"--- Q: [{q_label}] {q_text}")
        explicit = jurisdictions_in_query(q_text)
        print(f"    jurisdictions_in_query → {sorted(explicit) if explicit else '(empty)'}")

        emb = await openai.embeddings.create(
            model="text-embedding-3-small", input=q_text,
        )
        vec = "[" + ",".join(f"{x:.8f}" for x in emb.data[0].embedding) + "]"

        for p_label, profile in TEST_PROFILES:
            allow = allowed_jurisdictions(q_text, profile)
            allow_str = ("(no filter)" if allow is None
                         else "{" + ",".join(sorted(allow)) + "}")

            # Apply the filter the way the retriever does.
            if allow is None:
                rows = await pool.fetch(
                    "SELECT source, language, section_number, "
                    "       1 - (embedding <=> $1::vector) AS sim "
                    "FROM regulations "
                    "ORDER BY embedding <=> $1::vector LIMIT 3",
                    vec,
                )
            else:
                rows = await pool.fetch(
                    "SELECT source, language, section_number, "
                    "       1 - (embedding <=> $1::vector) AS sim "
                    "FROM regulations "
                    "WHERE jurisdictions && $2::text[] "
                    "ORDER BY embedding <=> $1::vector LIMIT 3",
                    vec, list(allow),
                )
            top = [f"{r['language']}/{r['source']}" for r in rows]
            print(f"    {p_label:12s} allow={allow_str:24s} top3={top}")
        print()


# ── Step D: replay calibration ──────────────────────────────────────────────

async def step_d_replay_baseline(pool: asyncpg.Pool, anthropic_client) -> None:
    print("\n" + "=" * 70)
    print("STEP D — web fallback replay on last 50 real hedges")
    print("=" * 70)

    from rag.web_fallback import attempt_web_fallback

    rows = await pool.fetch(
        "SELECT id, query, created_at FROM retrieval_misses "
        "WHERE created_at > NOW() - INTERVAL '60 days' "
        "ORDER BY created_at DESC LIMIT 50"
    )
    if not rows:
        print("  No hedges in retrieval_misses to replay.")
        return

    print(f"  Running fallback on {len(rows)} hedge queries…")
    surfaced = blocked_conf = blocked_dom = blocked_quote = noresult = 0
    persisted = 0

    for i, row in enumerate(rows, 1):
        q = row["query"]
        try:
            r = await attempt_web_fallback(
                query=q, anthropic_client=anthropic_client,
            )
        except Exception as exc:
            print(f"    [{i:2d}] {type(exc).__name__}: {str(exc)[:80]}")
            continue

        try:
            await pool.execute(
                "INSERT INTO web_fallback_responses "
                "  (is_calibration, query, web_query_used, top_urls, "
                "   confidence, source_url, source_domain, quote_text, "
                "   quote_verified, surfaced, surface_blocked_reason, "
                "   answer_text, latency_ms) "
                "VALUES (TRUE, $1, $2, $3::text[], $4, $5, $6, $7, $8, "
                "        $9, $10, $11, $12)",
                q, r.web_query_used, r.top_urls or [], r.confidence,
                r.source_url, r.source_domain, r.quote_text,
                r.quote_verified, r.surfaced, r.surface_blocked_reason,
                r.answer_text, r.latency_ms,
            )
            persisted += 1
        except Exception as exc:
            print(f"    [{i:2d}] persist failed: {exc}")
            continue

        if r.surfaced:
            surfaced += 1
            tag = "OK"
        elif r.surface_blocked_reason == "low_confidence":
            blocked_conf += 1
            tag = "lc"
        elif r.surface_blocked_reason == "domain_blocked":
            blocked_dom += 1
            tag = "dom"
        elif r.surface_blocked_reason == "quote_unverified":
            blocked_quote += 1
            tag = "qu"
        else:
            noresult += 1
            tag = "no"
        domain = r.source_domain or "-"
        print(f"    [{i:2d}] {tag:3s} conf={r.confidence or '-':>1} "
              f"dom={domain[:30]:30s} {q[:60]}")

    print(f"\n  Persisted: {persisted} / Surfaced: {surfaced}")
    print(f"  Blocked   confidence={blocked_conf}  domain={blocked_dom}  "
          f"quote={blocked_quote}  no_result={noresult}")
    print(f"  Surface rate: {100*surfaced/max(1,persisted):.1f}%")


# ── Main ────────────────────────────────────────────────────────────────────

async def main() -> None:
    dsn = os.environ["REGKNOTS_DATABASE_URL"].replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=4)
    openai = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

    try:
        await step_a_corpus_probe(pool, openai)
        await step_b_jurisdiction_matrix(pool, openai)

        # Step D needs Anthropic client.
        from anthropic import AsyncAnthropic
        anthropic = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        await step_d_replay_baseline(pool, anthropic)
        await anthropic.close()
    finally:
        await openai.close()
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

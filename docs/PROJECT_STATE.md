# RegKnot — Project State

**One-page operational snapshot for humans and fresh Claude Code sessions.**

Last updated: 2026-04-20 (post-Sprint-C3)

---

## TL;DR

RegKnot is a maritime-compliance RAG at **https://regknots.com**. Production stack live and healthy. 15 ingested regulation sources, ~42K chunks. Retrieval passes a vessel-type × CFR-Subchapter filter after Sprint C2, hitting 100% A on an internal 28-question regression set. Awaiting real pilot-user data before further retrieval tuning.

## Live production

- **App:** https://regknots.com
- **API health:** https://regknots.com/api/health — `{"status":"healthy"}`
- **VPS:** `root@68.183.130.3`
- **Repo paths:** local `C:\Users\Blake Marchal\Documents\RegKnots`, VPS `/opt/RegKnots` (NOT `/root/RegKnots`)
- **Alembic head:** `0045`
- **Services:** `regknots-api`, `regknots-web`, `regknots-worker` — all systemd, all active
- **DB:** `docker exec regknots-postgres psql -U regknots -d regknots`

## Corpus — 15 sources (~42,000 chunks)

| Source | Type | Chunks (approx.) | Freshness |
|---|---|---|---|
| `cfr_33` | CFR Title 33 — Navigation | 7,190 | Weekly via Celery |
| `cfr_46` | CFR Title 46 — Shipping | 10,523 | Weekly |
| `cfr_49` | CFR Title 49 — Transportation | 15,827 | Weekly |
| `colregs` | International/Inland Rules | 102 | Manual |
| `erg` | Emergency Response Guidebook 2024 | 762 | Monthly PHMSA watcher |
| `ism` | ISM Code | 63 | Manual |
| `ism_supplement` | MSC resolution amendments | 23 | Manual |
| `nvic` | USCG NVICs | 3,453 | Weekly |
| `solas` | SOLAS 2024 Consolidated | 1,034 | Manual |
| `solas_supplement` | MSC amendments to SOLAS | 12 | Manual |
| `stcw` | STCW Convention + Code | 532 | Manual |
| `stcw_supplement` | MSC amendments to STCW | 4 | Manual |
| `nmc_policy` | NMC policy letters + crediting guidance | 127 | Manual |
| `nmc_checklist` | MMC application/renewal checklists | 33 | Manual |
| `uscg_bulletin` | USCG GovDelivery (MSIBs, NMC announcements, ALCOASTs) | 2,232 | **Backfill only 2023-04 → 2026-04**; live feed pending |

## RAG pipeline — current architecture

1. **Router** (Haiku classifier) → picks Haiku/Sonnet/Opus per query complexity
2. **Retrieval** (pgvector HNSW + hybrid):
   - Query embedding (`text-embedding-3-small`)
   - Per-source-group diversified fetch
   - Identifier regex (UN1219, NVIC 04-08, etc.)
   - Broad keyword trigram
   - Merge with identifier +0.05 / keyword +0.02 boosts
3. **Vessel-type × CFR-Subchapter applicability filter** ⭐ (Sprint C2):
   - Drops CFR chunks from Parts that don't apply to the user's vessel type
   - Non-CFR sources (SOLAS/NVIC/NMC/bulletin/ERG) pass through
   - Mapping at `packages/rag/rag/retriever.py:_VESSEL_TYPE_CFR_APPLICABILITY`
4. **Rerank** — source-affinity boosts (+0.20/matched group) + vessel-profile text-match boost (+0.05/term)
5. **Synthesis** — Claude Sonnet 4.6 default, Opus for high-complexity
6. **Citation verification** — regex extracts cites, verifies each in DB; regenerates on unverified with feedback; strips any still-unverified

## Regression eval — baseline + progression

- Harness: `scripts/eval_rag_baseline.py` — 28 test queries × 5 vessel profiles
- Graded per-vessel as of C3 (no cross-vessel regex leakage)

| Sprint | A | A− | B | C | F | A-or-A− |
|---|---|---|---|---|---|---|
| Baseline | 23 | 3 | 0 | 0 | 2 | 92.9% |
| C1 (prompt) | 21 | 4 | 1 | 0 | 2 | 89.3% |
| C2 (filter) | 28 | 0 | 0 | 0 | 0 | 100% |
| **C3 (tightened grader, per-vessel expected)** | **28** | **0** | **0** | **0** | **0** | **100%** |

Grader tightened in C3 to use per-vessel expected regex (V1 expects `46 CFR 96.35-10`, V2 expects `35.30-20`, V5 expects `142.226`) + explicit `29 CFR 1910` in `wrong_sub` to catch OSHA hallucinations. Still 100% A — the filter + prompt changes are holding under stricter grading.

Latest eval artifact path: `data/eval/<timestamp>/summary.md` + `summary.json` (C3 run: `2026-04-20_192453`)

## Known issues & follow-ups

- **V5/F5 retrieval gap** (towing vessel CO2 system): the Subchapter M applicability table (`46 CFR 144.240`) isn't being surfaced by vector search; answer is honest-limit rather than wrong. Needs a retrieval-side promotion tuning pass.
- **Live GovDelivery feed not wired.** Bulletin corpus freshness stops at ~April 2026. Priority 1a on the roadmap: subscribe `alerts@regknots.com` + parse inbound emails.
- **Retrieval-side freshness filtering** not implemented. Columns are captured (published_date, expires_date, superseded_by) but not used in WHERE clauses. Priority 1b.
- **Notification system:** 3 issues documented (CFR weekly over-triggering, rollback-not-cascading, is_active-true default). Issues A/B fixed in previous sprint; Issue C still pending UI work.
- **NVIC adapter section-numbering:** still over-splits on enclosures (1,277 unique section_numbers vs ~160 real NVICs). Cosmetic, not functional.
- **CFR content-hash sensitivity:** threshold-gated (Sprint B3 fix), proper normalization deferred.

## Key docs (read if relevant to your task)

- `docs/roadmap.md` — full strategic roadmap with priorities & effort estimates
- `docs/sprint-audits/rag-architecture-audit-april-2026.md` — RAG architecture decisions + reasoning
- `docs/sprint-audits/nmc-ingest-and-forms-audit.md` — NMC ingest structural analysis
- `docs/sprint-audits/federal-register-discovery-gap-report.md` — why FR isn't a viable discovery channel for NVIC/NMC/MSIB
- `docs/sprint-audits/notification-system-issues.md` — notification UX follow-ups
- `docs/testing/retrieval-regression-test-plan.md` — 10 vessel setups × ~60 test questions for Karynn + pilots
- `docs/announcements/operator-update-april-2026.md` — Karynn-facing update on what changed
- `docs/chat-bring-up-prompt.md` — copy/paste bring-up prompts for Claude.ai / Desktop / Cowork
- `docs/cowork-task-prompts.md` — watertight prompts for the Cowork scheduled tasks (GovDelivery stager, weekly one-pager)

## Standing rules (non-negotiable)

- **Branch policy:** commit directly to main. Merge worktree → main at end of every task. User pushes manually.
- **Sister name:** Karynn (CEO, Unlimited Licensed Captain). **Never "Cassandra"** — grep before every commit.
- **Owner email:** `blakemarchal@gmail.com` hardcoded in `apps/api/app/routers/admin.py`. Karynn is `is_admin` but not Owner.
- **`packages/ingest/ingest/cli.py`:** DO NOT regenerate. Patch in place. Preserve `dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")` at `create_pool`.
- **Schema-first:** read actual table schemas before writing queries.
- **Propose spec, wait for greenlight** before coding non-trivial work.
- **Grep for Cassandra** before every commit.

## Test-question bank for Karynn + pilots

`docs/testing/retrieval-regression-test-plan.md` has:
- 10 reference vessel setups (V1 containership, V2 tanker, V3 Subchapter-T passenger, V4 Subchapter-K, V5 Subchapter-M towing, V6 fishing, V7 OSV, V8 ferry, V9 research, V10 liftboat)
- ~60 diagnostic questions bucketed by domain
- Expected-source cheat sheet for grading
- Feedback capture template

**Current plan:** Karynn runs 2-3 days of exhaustive testing first → harden based on her findings → then re-engage lapsed pilots with a "we heard you, we upgraded" note.

## Key scripts

- `scripts/eval_rag_baseline.py` — autonomous RAG regression harness
- `scripts/debug_retrieval.py` — replay any query against live retriever with vessel context
- `scripts/verify_filter.py` — standalone unit test for the Subchapter applicability filter
- `scripts/rollback_source.sh` — transactional corpus + notification rollback
- `scripts/ocr_scanned_nmc.py` — Claude Vision OCR for image-only PDFs
- `scripts/ingest_nvic_04-08.py` — one-off ingest for NVIC 04-08 Ch-2 (template for future Wayback-sourced gap fills)

## Recent shipped work (reverse chronological, last 10 commits)

```
a906051 feat(rag): Sprint C2 — vessel-type × CFR-Subchapter applicability filter
ee5cd72 feat(rag): Sprint C1 — prompt refresh cuts OSHA hallucinations 83%
abb37c7 docs: full RAG architecture audit with baseline-driven recommendations
0939766 feat(eval): autonomous RAG regression harness + baseline run
25f882b docs: retrieval-regression test plan + debug_retrieval.py
2868b9d docs: updated roadmap + Karynn-facing operator update
296094f fix(notify): collapse-per-source + bulk-republish gate + rollback cleanup
3f6085e fix(uscg_bulletin): rewrite filter (subject-only Pass 1 + LLM Pass 2)
fc469c2 chore: USCG bulletin smoke-test + ingest-report scripts
337e507 feat(rag): USCG GovDelivery bulletin source + freshness columns (Sprint B)
```

## How to resume in a fresh Claude Code session

Use the resumption prompt at the bottom of the last message in the prior thread, or this minimal version:

```
Context resumption — RegKnot. Read docs/PROJECT_STATE.md first, then
ask me for the task. Standing rules in project memory. No other
briefing needed.
```

# RegKnot — Project State

**One-page operational snapshot for humans and fresh Claude Code sessions.**

Last updated: 2026-09-26 (question-audit follow-up deployed, SOLAS / cfr_49 cleanup applied, Anthropic credits exhausted; audit `docs/sprint-audits/question-audit-2026-09-25.md`; Opus 5.5 low is the default answer model; system audit 2026-09-10)

---

## TL;DR

RegKnot is a maritime-compliance RAG at **https://regknots.com**. Production stack live and healthy. **91,892 chunks across 66 sources** (2026-09-26, after the SOLAS re-parse, the cfr_49 scope and stale-row prunes) with 100% embedding coverage. Retrieval pipeline now includes multi-query rewrite, Haiku reranker, citation oracle, source-diversified fetch, jurisdiction filter, vessel-profile boosts, synonym + intent expansion; hybrid BM25+dense built, measured 2026-07-19 and rejected (dense wins) — prod `.env` carried it switched on until the 2026-09-10 fix, now dense. **96.1% A-or-A−** on the latest 152-question regression eval. First organic Captain-tier subscriber 2026-09-09. See the 2026-09-10 audit for the pre-push list.

## Live production

- **App:** https://regknots.com
- **API health:** https://regknots.com/api/health — `{"status":"healthy"}`
- **VPS:** `root@68.183.130.3` (shared box, hostname `spiritflow-prod-01`)
- **Repo paths:** local `C:\Users\Blake\Documents\RegKnots`, VPS `/opt/RegKnots` (NOT `/root/RegKnots`)
- **Alembic head:** `0115`
- **Services:** `regknots-api`, `regknots-web`, `regknots-worker` — all systemd, all active
- **DB:** `docker exec regknots-postgres psql -U regknots -d regknots` (PG 16.13 + pgvector, 1528 MB)
- **Deploy:** `scripts/deploy.sh` + `scripts/smoke.sh` (shipped 2026-05-07; 3-stage smoke catches stale-build failure mode)

## Standing rules (non-negotiable)

- **Branch policy:** commit directly to main. Merge worktree → main at end of every task. User pushes manually.
- **Sister name:** Karynn (CEO, Unlimited Licensed Captain). **Never "Cassandra"** — grep before every commit.
- **Owner email:** `blakemarchal@gmail.com` hardcoded in `apps/api/app/routers/admin.py`. Karynn is `is_admin` but not Owner.
- **`packages/ingest/ingest/cli.py`:** DO NOT regenerate. Patch in place. Preserve `dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")` at `create_pool`.
- **Schema-first:** read actual table schemas before writing queries.
- **Propose spec, wait for greenlight** before coding non-trivial work.
- **Grep for Cassandra** before every commit.

## Corpus snapshot — 106,041 chunks across 66 sources (live 2026-09-10; 92,336 on 2026-09-26, see `docs/corpus-status.md`)

100% embedding coverage. Vector dim 1536. ~108.9M chars / 27.2M tokens. Top sources by chunk count:

| Source | Chunks | Notes |
|---|---|---|
| `cfr_49` | 15,838 | Title 49 — Transportation; per-row 172.101 hazmat chunking (D6.16b) |
| `cfr_46` | 10,523 | Title 46 — Shipping |
| `cfr_33` | 7,192 | Title 33 — Navigation |
| `nma_rsv` | 5,426 | Norway NMA RSR/RSV/SM circulars |
| `nvic` | 3,453 | USCG NVICs |
| `uscg_msm` | 3,048 | USCG Marine Safety Manual (last refresh 2021-09 — stale) |
| `iacs_ur` | 2,981 | IACS Unified Requirements |
| `nmc_exam_bank` | 2,938 | NMC exam-bank ingest (D6.83 Phase A1, 2026-05-07) |
| `uscg_bulletin` | 2,232 | GovDelivery backfill 2023-04 → 2026-04; live feed pending |
| `imdg` | 2,129 | IMDG Code Vol 1+2 (Amdt 42-24); per-row DGL chunking |

Plus 40 additional sources: `cfr_*`, `solas`, `marpol`, `colregs`, `stcw`, `ism` (+ supplements), `usc_46`, `who_ihr`, `erg`, `nmc_policy` / `nmc_checklist`, foreign-flag (UK MCA, AMSA, MPA, MarDep, LISCR, IRI, BMA, NMA), IMO codes (HSC, IGC, IBC, CSS, Load Lines), and OCIMF public layer. See `docs/corpus-status.md` for the full table, tier classifications, and curated-vs-full coverage notes.

**Embedding model:** `text-embedding-3-small` (April + May audits both agree the upgrade to `-large` is not the bottleneck).

**Stale outliers:** STCW (2017-07), ISM (2018-07), USCG MSM (2021-09), MARPOL (2022-11). `stcw_amend` / `marpol_amend` carry the deltas. Acquisition plan for missing IMO instruments (ISPS, LSA, FSS, IS Code, Load Lines, IAMSAR, BMP MS): `docs/roadmap.md` §IMO.

## RAG pipeline — current architecture

1. **Router** (Haiku classifier) — off-topic gate plus a complexity score 1–3 (D6.75 tightened), which is logged. Since 2026-09-23 the score no longer picks the answer model: `SYNTHESIS_MODEL_FLOOR` (default `claude-opus-5-5`) lifts every pick to Opus 5.5. Empty restores Haiku / Sonnet / Opus routing.
2. **Pre-retrieval distillation** (D6.51) for verbose first turns
3. **Multi-query rewrite** (D6.66) — Haiku produces 2-3 reformulations; default ON
4. **Synonym + intent expansion** — `synonyms.py` (lifejacket/log/mob/stability/stencil), drill-frequency + equipment-marking intent expanders
5. **Retrieval** (pgvector HNSW + per-source-group diversified fetch + identifier regex + broad keyword trigram, merged with boosts). As of 2026-09-25 (deployed 2026-09-26):
   - SOLAS regulation and CFR section/part citations resolve against `section_number`, not a `full_text` substring. A cited section keeps up to 5 chunks.
   - Identifier search runs only on the user's own words, not on reformulations.
   - Groups that cannot match the jurisdiction filter are skipped.
   - Reformulation retrievals start when the rewrite returns.
6. **Hybrid BM25 + dense (RRF)** — built and **dark-launched** behind `HYBRID_RETRIEVAL_ENABLED=False` (D6.71)
7. **Jurisdiction filter** — `jurisdictions text[]` array overlap (`&&`); 9-flag severance regression passes 9/9. Since 2026-09-24 it falls back to `users.jurisdiction_focus` when the vessel flag is Unknown.
8. **Vessel-type × CFR-Subchapter applicability filter** (Sprint C2) + **Subchapter M / TSMS source affinity** (D6.69). 2026-09-25: Title 46 only; it had been dropping 33/49 CFR parts that share a 46 CFR part number.
9. **Haiku reranker** (D6.66), output as `[index, score]` pairs since 2026-09-25, + source-affinity / vessel-profile / title boosts
10. **Citation oracle** (D6.70 Layer-2 retrieval intervention)
11. **Synthesis** — **Opus 5.5 for every answer** (2026-09-23; effort `low` on the stream, `high` on regeneration; 16K cap) after a six-way comparison (`scripts/compare_synthesis_models.py`, LLM surface audit §5). In router-only mode Sonnet 5 streams at effort `low` with `_MAX_TOKENS` 8192. The 14.5K-token system prompt is prompt-cached (2026-09-22).
12. **Hedge judging** (D6.60) → cascading ensemble web fallback (D6.59), Big-3 (Claude + GPT + Grok, D6.58)
13. **Citation verification** — regex extracts cites, verifies in DB, regen on unverified, strips remainders
14. **Token-by-token streaming** on the chat path (D6.68)

## Recent shipped work (reverse chronological)

168 commits since 2026-04-22 (last PROJECT_STATE refresh). Selected highlights:

- **2026-05-07 (D6.83 + Sprint B):** `/education` landing page; Study Tools toggle propagates to nav without refresh; account toggle to hide Quizzes & Guides; Phase A5 + quiz bug fixes; A4 take-the-quiz interactive flow; A3 frontend `/study`; A2 backend (router + persistence); A1 curated `nmc_exam_bank` ingest adapter
- **2026-05-07:** `scripts/deploy.sh` + `scripts/smoke.sh` (boring deploys; 3-stage smoke)
- **D6.82:** marketing-copy move of 4 AI Co-Pilots from Captain to Mate
- **D6.81:** unify role/persona to one source of truth
- **D6.80:** soft archive for conversations + mobile-compact EmptyState
- **D6.79:** auto-populate vessel selector when opening a chat from history
- **D6.77 / D6.78:** morning UX polish from Karynn's testing list; short VesselPill labels
- **D6.75 / D6.76:** weekly NMC corpus refresh via systemd timer; 35 triaged NMC PDFs declared; `_MAX_TOKENS` bump 2048→8192; classifier "tell me about X" → Sonnet not Opus
- **D6.74:** chat "keeps stopping mid stream" UX gap fix
- **D6.71:** hybrid BM25 + dense retrieval foundation (dark-launched)
- **D6.70:** citation oracle (Layer-2 retrieval intervention)
- **D6.68:** token-by-token streaming on chat path
- **D6.67:** expand credential types + smarter scanner prompt
- **D6.66:** multi-query rewrite + Haiku reranker + title-boost
- **D6.64:** vessel/PSC/changelog/audit AI co-pilots; nautical loading filler
- **D6.63:** personalized reasoning — chat + Co-Pilot cards + Career Path
- **D6.62:** mariner vault sea-time logger + PDF credential package
- **D6.60 / D6.59 / D6.58:** hedge judge; cascading ensemble; Big-3 web fallback (Claude + GPT + Grok); off-topic scope gate; hedge audit feedback loop; web fallback events admin page
- **D6.55–D6.49:** Wheelhouse / crew-tier — billing wired end-to-end, workspace-scoped chat, pending invites, OnboardingGate skip, invite signup flow
- **D6.51:** pre-retrieval query distillation for verbose first turns
- **D6.50:** OCIMF public layer (SIRE 2.0 + Information Papers)
- **C3 / Sprint D1 (pre-2026-04-22):** per-vessel grader (100% A); admin-only weekly NMC digest, retire `nmc_memo`

Run `git log --oneline --since="2026-04-22"` for the complete list.

## Known issues & open items (per 2026-09-10 audit)

Full findings, evidence and the awaiting-go fix spec: `docs/sprint-audits/full-system-audit-2026-09-10.md`.

**Fixed 2026-09-10 (same day, on go):** prod flipped to dense retrieval (`HYBRID_RETRIEVAL_ENABLED=false`; had been `true` since May against the July verdict); MAERSK Kinloss flag set to `United States`; scheduled Celery ingest wrapped in `run_ingest.sh`; non-concurrent monthly REINDEX task removed; `uv.lock` regenerated. Verification: her four questions 4/32 → 0/32 foreign-flag hits; harness 0.823 / 0.658 (July 0.790 / 0.627).

**P1 remaining:**
- ~~`amount_paid = 3900`~~ **Answered 2026-09-26:** the price is mapped, but it is the legacy Pro price at $39.00 while the site advertises $39.99. Blake decides which way to align.
- **Stripe webhook endpoint** is missing `customer.subscription.created` and `.deleted`. The daily `reconcile_subscriptions` task covers deletions within ~3 days. Blake: add both events.
- **51 of 56 vessel profiles have `flag_state = Unknown`.** Roadmap item 6 (derive scoping from `jurisdiction_focus`, confirm-your-flag prompt, IMO-number enrichment) is the top product item.

**P2:**
- ~~Stripe first-purchase `billing_interval` NULL~~ Fixed 2026-09-26 (`4f19025`), and the intervals were backfilled from Stripe.

**From the 2026-09-25 question audit (details in the audit doc, §6 for 2026-09-26):**
- **Done 2026-09-26:**
  - Stale corpus rows: `ingest/prune.py` plus the SOLAS parser fix. SOLAS went from 1,739 to 848 chunks, with the removed rows kept in `data/pruned/`.
  - cfr_49 is scoped to its maritime parts: 15,967 → 3,145 chunks.
  - Gold pairs A25-1 to A25-7 added.
- **Deployed 2026-09-26 (`51231cc`, verified on prod first):**
  - The recovery gate counts citations in the answer, and the corpus oracle runs on `partial_miss`.
  - Analytics run after `done`: last token → `done` 3.7 → 0.0 s on normal answers, 9.3 → 4.4 s on hedged ones.
  - Credential reminders appear only when asked.
- **Harness baselines** (71 pairs, clean corpus): dense 0.8592 / 0.6924, dense-prod 1.0000 / 0.7301.
- **Incident, 2026-09-26 00:15 to ~02:10 UTC:** Anthropic credits were exhausted and the GPT-4o fallback served. No user traffic during the outage; resolved.

**Still open from May:** `next@15.5.14` DoS CVE (bumped to 15.5.26 in `6976759`, awaiting push); ~~Sentry `environment` tag~~ (done 2026-09-26); ~~no CI~~ (GitHub Actions since 2026-09-26); SpiritFlow co-tenancy; offsite backups (Blake's DO Spaces step); STCW 2017 / MARPOL 2022 / MSM 2021 bases; Load Lines 3 chunks; FSS / LSA resolution-only.

**Resolved since the May audit:** shared LLM helpers (`packages/rag/rag/llm.py`, 2026-09-22) and the first `apps/api` tests (`apps/api/tests/`), JWT secret, `.env` 600, daily + restore-tested backups, cgroup caps, swap, `run_ingest.sh`, Layer C, NVIC OCR, eval harness, migration 0115 (fallback persist), Anthropic key rotation.

## Operational data

- `retrieval_misses` (migration 0047) — auto-logs hedged chat answers with query, vessel_profile, top-8 chunks, citations, model/tokens, 2KB answer preview. Query: `SELECT query, vessel_profile_set, hedge_phrase_matched FROM retrieval_misses ORDER BY created_at DESC LIMIT 20;`
- `hedge_audits` (D6.60) — Haiku gate decisions on whether to fire fallback
- `retrieval_misses` baseline: 5-10% of real chat responses hedge

## Key docs (read if relevant to your task)

- `docs/sprint-audits/full-system-audit-2026-05-08.md` — **canonical audit; supersedes the April version on every numeric**
- `docs/roadmap.md` — full strategic roadmap (rewritten in the 2026-05-08 audit pass)
- `docs/corpus-status.md` — engineering counterpart to `/coverage`; full source table, tiers, blocked/translation-deferred
- `docs/sprint-audits/rag-architecture-audit-april-2026.md` — earlier RAG architecture decisions (predates hybrid, oracle, multi-query, Haiku reranker, web fallback cascade — read with the 2026-05-08 audit)
- `docs/sprint-audits/notification-system-issues.md` — notification UX follow-ups
- `docs/testing/retrieval-regression-test-plan.md` — 10 vessel setups × ~60 questions for Karynn + pilots
- `docs/announcements/operator-update-april-2026.md` — Karynn-facing update on what changed
- `docs/chat-bring-up-prompt.md` — copy/paste bring-up prompts for fresh sessions
- `docs/cowork-task-prompts.md` — Cowork scheduled-task prompts (GovDelivery stager, weekly one-pager)
- `docs/corpus-gap-analysis.md` — ranked corpus gaps with ingest-cost estimates

## Key scripts

- `scripts/deploy.sh` + `scripts/smoke.sh` — canonical deploy + 3-stage smoke probe
- `scripts/eval_rag_baseline.py` — autonomous RAG regression harness
- `scripts/debug_retrieval.py` — replay any query against live retriever with vessel context
- `scripts/verify_filter.py` — standalone unit test for the Subchapter applicability filter
- `scripts/rollback_source.sh` — transactional corpus + notification rollback
- `scripts/ocr_scanned_nmc.py` — Claude Vision OCR for image-only PDFs
- `scripts/generate_sailor_queries.py` + `data/eval/sailor_queries.json` — 90 synthetic mariner-voice eval questions
- `packages/rag/rag/hedge.py` — shared hedge-phrase patterns
- `packages/rag/rag/authority.py` — source → authority tier mapping

## How to resume in a fresh Claude Code session

```
Context resumption — RegKnot. Read docs/PROJECT_STATE.md first, then
ask me for the task. Standing rules in project memory. No other
briefing needed.
```

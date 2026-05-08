# RegKnot — Project State

**One-page operational snapshot for humans and fresh Claude Code sessions.**

Last updated: 2026-05-07 (post D6.83 + Sprint B `/education`, post full-system audit 2026-05-08)

---

## TL;DR

RegKnot is a maritime-compliance RAG at **https://regknots.com**. Production stack live and healthy. **77,111 chunks across 50 sources** with 100% embedding coverage. Retrieval pipeline now includes multi-query rewrite, Haiku reranker, citation oracle, source-diversified fetch, jurisdiction filter, vessel-profile boosts, synonym + intent expansion; hybrid BM25+dense built and dark-launched. **96.1% A-or-A−** on the latest 152-question regression eval. Marketing push imminent — see audit for the three pre-walk-away items.

## Live production

- **App:** https://regknots.com
- **API health:** https://regknots.com/api/health — `{"status":"healthy"}`
- **VPS:** `root@68.183.130.3` (shared box, hostname `spiritflow-prod-01`)
- **Repo paths:** local `C:\Users\Blake Marchal\Documents\RegKnots`, VPS `/opt/RegKnots` (NOT `/root/RegKnots`)
- **Alembic head:** `0092`
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

## Corpus snapshot — 77,111 chunks across 50 sources

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

**Stale outliers:** STCW (2017-07), MARPOL (2022-11), USCG MSM (2021-09). MARPOL is the highest user-visible risk. Quarterly refresh sprint pending.

## RAG pipeline — current architecture

1. **Router** (Haiku classifier) → Haiku/Sonnet/Opus per query complexity (D6.75 tightened)
2. **Pre-retrieval distillation** (D6.51) for verbose first turns
3. **Multi-query rewrite** (D6.66) — Haiku produces 2-3 reformulations; default ON
4. **Synonym + intent expansion** — `synonyms.py` (lifejacket/log/mob/stability/stencil), drill-frequency + equipment-marking intent expanders
5. **Retrieval** (pgvector HNSW + per-source-group diversified fetch + identifier regex + broad keyword trigram, merged with boosts)
6. **Hybrid BM25 + dense (RRF)** — built and **dark-launched** behind `HYBRID_RETRIEVAL_ENABLED=False` (D6.71)
7. **Jurisdiction filter** — `jurisdictions text[]` array overlap (`&&`); 9-flag severance regression passes 9/9
8. **Vessel-type × CFR-Subchapter applicability filter** (Sprint C2) + **Subchapter M / TSMS source affinity** (D6.69)
9. **Haiku reranker** (D6.66) + source-affinity / vessel-profile / title boosts
10. **Citation oracle** (D6.70 Layer-2 retrieval intervention)
11. **Synthesis** — Claude Sonnet 4.6 default, Opus for high-complexity; `_MAX_TOKENS` 8192 (D6.75)
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

## Known issues & open items (per 2026-05-08 audit)

**Critical / pre-marketing-push (each <30 min):**
- **JWT signing-key mismatch** — `.env` has `REGKNOTS_SECRET_KEY` but code reads `REGKNOTS_JWT_SECRET_KEY`; API is signing with hardcoded default. **Fix before traffic arrives.** See audit TL;DR #1.
- **`.env` is mode 0644** — co-tenant `spiritflow` user can read every secret. `chmod 600`. Audit TL;DR #2.
- **Zero Postgres backups.** RPO=∞. Cron'd `pg_dump` snippet in audit TL;DR #3.

**High:**
- `regknots-refresh-weekly.service` failed since 2026-05-03 (`code=203/EXEC`); weekly CFR + bulletin refresh hasn't run for 5 days
- `next@15.5.14` has DoS CVE GHSA-q4gf-8mx6-v5v3 (fix in 15.5.15)
- Service crashloop history: `regknots-api` 116 restarts + 1 OOM-kill / 14d. Add 2 GB swap + `MemoryMax` on systemd units
- Shared tenancy with SpiritFlow on a 4 GB box; SpiritFlow OOMs can take API down
- **Zero tests.** `apps/api/tests/` doesn't exist; `apps/web` has no test runner. 28+ fix commits in 14d, zero reverts — pace is high but no safety net
- LLM-helper duplication: Sonnet boilerplate copy-pasted 6× in `me.py`; `_parse_json` exists in 6 files

**Medium:**
- Hybrid BM25 + dense is dark-launched; flip `HYBRID_RETRIEVAL_ENABLED=true` and re-eval
- Synthesis still invents OSHA citations on ~21% of occupational-safety questions; verifier strips them and regen fires. Add explicit no-cite clause to `prompts.py`
- No CI workflow; no external alerting (Sentry-only); no security headers (HSTS/CSP/etc.) on Caddy
- Stripe webhook handler re-raises `str(exc)` to Stripe with no logging (`billing.py:68-71`)
- `auth.py:184-199` swallows three sequential email-send failures on register with zero log signal

**Resolved (memory was stale):**
- Vocab mismatch (`lifejacket`/`log`/etc.) — `synonyms.py` + multi-query rewrite shipped
- `ism_supplement` migration drift — canonical source list now in migration `0090`

See `docs/sprint-audits/full-system-audit-2026-05-08.md` for the full Verdict matrix and 30-day priority order.

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

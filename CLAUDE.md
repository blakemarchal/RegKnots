# RegKnots — Claude session brief

This file is auto-loaded by Claude Code in any session opened from this repo. It is the canonical short-form bring-up replacement for `docs/chat-bring-up-prompt.md`. **Read it before starting work.**

For a deeper read, follow the pointers at the end.

---

## What this is

RegKnots — maritime-compliance copilot for U.S. commercial vessel operators. Live at https://regknots.com.

- **Karynn Marchal** — CEO, USCG Master Unlimited, active containership Captain. Email `kdmarchal@gmail.com`. **Never call her "Cassandra"** — grep for it before every commit.
- **Blake Marchal** — CTO, engineer. Email `blakemarchal@gmail.com` (hardcoded as the Owner in `apps/api/app/routers/admin.py`). Karynn is `is_admin` but not Owner.

## Standing rules (non-negotiable)

- **Branch policy:** commit directly to main. Merge the worktree branch to main at the end of every task. User pushes manually unless they explicitly ask you to push.
- **Schema-first:** read actual table schemas before writing queries. Don't infer columns from a model class — query `information_schema` or read the latest alembic migration.
- **Propose spec, wait for greenlight** before coding non-trivial work. The user will say "go" or push back.
- **`packages/ingest/ingest/cli.py`:** DO NOT regenerate from codegen. Patch in place. Preserve the line `dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")` near `create_pool` — it adapts the asyncpg URL for the sync ingest path. If you regenerate this file, dispatch breaks.
- **Deploy procedure:** production runs from `origin/main` via `scripts/deploy.sh`. Never edit on the VPS. After every push to main, run `scripts/deploy.sh` from your laptop to roll the change.
- **Two schedulers exist.** systemd timers (`deploy/systemd`; the four corpus-refresh timers were **disabled 2026-08-10**, backup + db-maintenance stay on) AND Celery Beat (`apps/api/celery_beat.py`: weekly `update_regulations` for cfr_33/46/49/nvic, monthly REINDEX, digests, reminders). Disabling one does not disable the other. Check both before assuming a job is off.
- **Ad-hoc ingest jobs MUST use `scripts/run_ingest.sh`**, not `uv run python -m ingest.cli` directly. The wrapper isolates the job inside a transient systemd unit with a 1.5 GB memory cap so a runaway can't take the box. Plain interactive ingests caused 12 of 13 OOM events / 14 days per the 2026-05-08 audit. There is no good reason to bypass the wrapper.
- **Grep for "Cassandra" before every commit.** It's a recurring slip.

## How to verify state (don't trust memory; query the source)

| Question | Authoritative answer |
|---|---|
| Current alembic head | `cd apps/api && uv run alembic current` (or SSH the VPS for prod) |
| Corpus inventory | `docs/corpus-status.md` (refreshed regularly) |
| What shipped recently | `git log --oneline --since="14 days ago"` |
| Deploy state of prod | `scripts/smoke.sh` (content-asserts JS-chunk canary strings) |

If a doc says "alembic head is 0045" but `alembic current` says `0092`, the doc is stale — flag it. Several have been; see the 2026-05-08 audit.

## Repo layout (one-line each)

- `apps/api/` — FastAPI service. Routers in `app/routers/`. Migrations in `alembic/versions/`.
- `apps/web/` — Next.js 15 app router. Pages in `src/app/`. Auth-gated routes use `<AuthGuard>`.
- `packages/rag/` — retrieval, router, synthesis, citation oracle, hedge judge, web fallback (~23 modules in `rag/`).
- `packages/ingest/` — corpus adapters + chunker + embedder. Source-specific adapters under `ingest/sources/`.
- `infra/` — Postgres + Redis docker-compose. Production systemd units.
- `scripts/` — `deploy.sh`, `smoke.sh`, eval harness, OCR helpers, brand assets.
- `docs/` — `PROJECT_STATE.md` is the canonical operational snapshot. `roadmap.md` for strategy. `sprint-audits/` for the latest deep audits.

## Production access

- **VPS:** `root@68.183.130.3` (hostname `spiritflow-prod-01` — shared with another tenant, RegKnots' repo lives at `/opt/RegKnots`).
- **Postgres:** Docker container `regknots-postgres`. `docker exec regknots-postgres psql -U regknots -d regknots -c "..."`.
- **Services:** `regknots-api`, `regknots-web`, `regknots-worker` (systemd).
- **Caddy:** `/etc/caddy/Caddyfile` — TLS via ACME, on-demand certs gated by `/api/domain-check`.
- **Logs:** journald. `journalctl -u regknots-api -n 100 --no-pager`.

## Operating norms

- The codebase ships fast (D6.83 = 83 sub-sprints inside the D6 series alone). Sprint-tagged comments (e.g., `// Sprint D6.83 Phase A5 —`) are pervasive; preserve them when editing.
- The user (Blake) is fluent in the codebase — be terse, grounded, and skip over the obvious. When you find something interesting, surface it; don't bury it.
- "Karynn says X" usually means a real user-found bug. Trust it and reproduce before second-guessing.
- The product has paying users. Risk-rank changes accordingly: a frontend fix on `/study` is low-risk; an alembic migration that drops a column is high-risk.
- **Anthropic spend (Blake, 2026-09-26): don't spend credits unless there is real value.** The product barely covers its VPS bill, and a day of audit probes helped drain the balance to zero. No Claude-calling probes, smokes, `--arm dense-prod` runs or model comparisons unless the result clearly matters, e.g. verifying a user-facing change that can't be checked any other way. Say what it costs first. Prefer code reading, unit tests, read-only SQL and the `dense` harness arm (OpenAI embeddings only).

## What was just done (last 14 days, headline only)

- D6.83 Sprint A1-A5: Study Tools — quiz + study guide generators, take-the-quiz mode, citation verification, PDF export. NMC exam-bank ingest (244 sections / 2,938 chunks).
- D6.83 Sprint B: `/education` landing page, persona pre-set on signup, `cadet_student`/`teacher_instructor` post-onboarding redirect to `/study`.
- D6.83 Account toggle: `users.study_tools_enabled`, hidden from nav when off.
- 2026-05-07: `scripts/deploy.sh` + `scripts/smoke.sh` shipped — closes the "no auto-deploy" gap; smoke probes are content-asserting (HTTP 200 + JS-chunk canary string), not status-only.
- 2026-05-08: full-system audit at `docs/sprint-audits/full-system-audit-2026-05-08.md`. Two critical-but-fixable findings (JWT secret env-var mismatch, no DB backups) flagged for pre-marketing-push fix.
- 2026-05-09 D6.84 Sprint A: confidence tier router shipped in **shadow mode** on prod. Adds 4-tier provenance (✓ Verified / ⚓ Industry Standard / 🌐 Relaxed Web / ⚠ Best-effort) on top of today's pipeline. Closes the partial_miss-low-web dead zone where Jordan Dusek's gasket-class questions hedged. Flag: `CONFIDENCE_TIERS_MODE=off|shadow|live`. Migration 0093 adds `tier_router_shadow_log` table + `messages.tier_metadata` JSONB. Admin compare view at `/admin/tier-router`. 12/12 unit tests pass. Gold set at `data/eval/tier_router_gold.json`. **Phase E flip to `live` is operator-driven.**
- 2026-05-22 D6.97 Sprint B: SOLAS re-parse with per-Regulation granularity. 81 Part-level → 379 per-Regulation Sections so "SOLAS Ch.III Reg.6" structured-matches against a real `section_number` instead of falling through to keyword search. Karynn's Maersk-onboard SART/comms question motivated.
- 2026-05-23 D6.97 Sprint C: **Precision Mode** + **Authority Hierarchy** prompt block shipped. Precision Mode is a per-user toggle on `/account` (col `users.precision_mode_enabled`, default OFF) that swaps in a stricter synthesis posture refusing unverified claims. Authority Hierarchy is always-on — 3 decision rules + BAD/GOOD example so US-flag fire-equipment queries lead with 46 CFR, not SOLAS.
- 2026-05-25 D6.97 Sprint #47 + #50: Per-Reg splitting for **all 10 IMO codes** (IBC 1→7 chapters, CSS 1→7, BWM 9→50, IGF 2→7, Polar 4→6; FSS/LSA/HSC/IGC/Load Lines chapter-level held). Tier 2 chunk-level enrichment (Sonnet 8-12 maritime aliases per chunk, prepended as `[Search terms:]` block) now applied to all IMO sources. Tier 1 maritime jargon synonyms added in `synonyms.py` (FF, IMO sticker, SCBA, EEBD, FCP, fireman's outfit) + extractor short-token carve-out (unlocked ~13 dead-code 2-3 char glossary entries — mob, gps, ais, psc, etc.).
- 2026-05-25 D6.97 Sprint #48: **IMO graphical-symbol resolutions** ingested (A.952(23) FCP symbols, A.760(18) + A.1116(30) LSA/escape signs). 5 sections / 25 chunks under new `imo_symbols` source. Karynn's IMO-sticker hedge can now cite directly.
- 2026-05-25 D6.97 Sprint #51: **Jurisdiction backfill** for 5 mis-tagged sources (cy_dms, pa_mmc, au_statutes, nscv, nmc_exam_bank). 7,343 chunks re-tagged from `['intl']` to their proper flag tags. Caught while verifying Karynn's query for US-flag profile — Cyprus DMS was appearing at rank 7 because it was leaking across flags.
- 2026-05-25 D6.97 Sprint #49: **Whale zones map** at `/whale-zones`. Public Leaflet page rendering 11 NOAA Fisheries North Atlantic Right Whale Seasonal Management Areas (50 CFR 224.105). Maersk-demo asset; sets up later AIS / vessel-proximity warning if GPS opt-in.
- 2026-05-27 D6.97 Sprint #54: **COSWP 2025 ingested** — UK MCA Code of Safe Working Practices for Merchant Seafarers, 2025 Edition. Karynn provided the 544-page Open Government Licence v3 PDF as the priority for the shore-side compliance officer pivot. Parser splits at `N.N` section headers, yields 357 sections across 34 chapters. New source: `coswp`, tagged `['uk']`, UK query-signal pattern recognizes "COSWP" or "Code of Safe Working Practices" so non-UK users can invoke it. **`CorpusBadges.tsx` + `docs/corpus-status.md` updated to reflect post-pivot corpus.**

- 2026-06 (audit sprint): quality audit of live user questions shipped: follow-up retrieval composition (short mid-thread messages), CG-form identifier retrieval (Karynn's "835"), never-assert-non-existence prompt rule, **MLC 2006 ingested** (140 sections — the labour fourth pillar; Nirmal's provisions gap), IMO MEPC/MSC resolution harvest Phase 1 (12 resolutions, `imo_mepc`/`imo_msc`), SIRE 2.0 Q Library completed (Pt2, + `ocimf` affinity group it never had), whale-zones nav + 4-feature polish + opt-in GPS persistence (migration 0112).
- **2026-07-18 model refresh (Fable audit session):** all Sonnet call sites → `claude-sonnet-5`, Opus → `claude-opus-4-8` (router MODEL_MAP, REGENERATION_MODEL, engine, web_fallback, checklists, study, documents, me, credentials, enricher, stcw/ism Vision). IDs live-validated against the prod key pre-ship. `chat.py _MODEL_ALIAS` got the new keys ADDED (old keys kept — D6.73 NULL-model_used lesson). Also fixed badly-rotted `chat.py _MISSING_SOURCES` that was telling users MARPOL/MLC/IMDG/IGC/IBC/CSS/BWM/Polar were "not in the database" (all long since ingested).
- **2026-07-19 "Wk1-4" mega-wave (Blake greenlit the full 30-day plan):**
  - **Hybrid verdict — DO NOT FLIP.** New `scripts/eval_retrieval.py` (retrieval-only recall@k/MRR, imports the eval_rag_baseline gold set). Dense 0.790 strong-recall@8 / 0.627 MRR vs hybrid RRF 0.548 / 0.416 — hybrid loses 16 pairs, gains 1 (lexical lane vetoes dense's correct hits via rank-blind RRF). ⛔ MEASURED comment on the config flag; evidence in `data/eval/retrieval/`; verdict doc `docs/hybrid-retrieval-verdict-2026-07-19.md`. ef_search 100 "measured zero effect" — invalid test (asyncpg RESET ALL wiped the pool-init SET; correction in the verdict doc, 2026-09-24). **Any retrieval change now runs this harness first.** Baselines to beat: **dense 0.8608/0.7046** (79-pair gold set, after the 2026-09-26 MARPOL split); **dense-prod 1.0000/0.7301** (71-pair set, 2026-09-26; not re-run on 79). The `dense` arm does not exercise query rewrite, reformulations or the reranker; a change to those must be measured with `--arm dense-prod`. A reformulation change shipped on dense-only probes on 2026-09-25 and was reverted the next day (−4 pairs on dense-prod). (The 2026-09-10 re-run gave 0.823/0.658, after prod was flipped back to dense; it had been serving hybrid since May against this verdict.)
  - **Per-ingest REINDEX removed** (held ACCESS EXCLUSIVE during live traffic); weekly `REINDEX CONCURRENTLY` + VACUUM + backup-staleness gate via `regknots-db-maintenance.timer` (installed, first run green: 245s reindex, no locks). Opt-in per-run: `REGKNOTS_REINDEX_AFTER_INGEST=1`.
  - **Backups proven restorable** — first restore test in project history: 762MB dump → clean pgvector/pg16 container, 421s, 0 errors, embeddings + alembic head verified. Runbook `docs/runbooks/db-restore.md`. Offsite scaffolding installed (rclone script + disabled timer) — **awaiting Blake's 5-min DO Spaces bucket+keys step**. `smoke.sh` now probes backup age every deploy.
  - **Citation trust pack:** chips amber→teal (amber now = caution only), "Corpus-verified · N citations" badge, message timestamps, aria-live streaming, pinch-zoom unlock, prefers-reduced-motion.
  - **Per-answer exports:** copy-with-citations + print-to-PDF (letterhead artifact) on every completed answer (`lib/answerExport.ts`).
  - **Persona-aware nav + starters:** shore_side_compliance/legal_consultant get Compliance Tools promoted, "Fleet"/"Credentials" labels, sea-time tools hidden, compliance-register starter prompts; cadets get Study-first. Ordering/visibility only, never capability.
  - **Fleet Audit Readiness LIVE:** `/me/audit-readiness?workspace_id` fan-out implemented (was stubbed) — workspace vessels + ≤12 members' records, fleet-framed findings, card on workspace page + dated PDF report export.
  - **Live-context chat injectors** (`rag/live_context.py`): "what changed in the regs this month?" → auto-injected recent-ingest summary (window parsed from query); "which whale zones are active?" → chat.py computes today's SMA status. Fail-open, append-only. 18 unit tests.
  - **Team audit log:** `GET /workspaces/{id}/audit-log` (JSON/CSV) + workspace-page section + `apiDownload()` — who asked what, when, with citations.
  - **Maersk demo script:** `docs/maersk-demo-script.md` (15-min arc, all shipped features).
  - Fixed 8 pre-existing "Cassandra" slips in code/docs. **Purchases (paywalled IMO data) remain DEFERRED per Blake.**

- **2026-08-10 incident session:** Anthropic credits hit zero on 08-09 → every Claude call 400 → GPT-4o fallback engaged and then **failed to persist** — `messages_model_used_check` never allowed `fallback_gpt4o`; 13 answers for one user were generated, billed and discarded. Migration **0115** widens the constraint. Anthropic key rotated; a carriage-return byte in `.env` blanked the key for every service until found (`file /opt/RegKnots/.env` after any edit). Four corpus-refresh timers disabled. Deployed `a4e75a4`.
- **2026-09-09:** first organic Captain-tier purchase (cassclark.425@gmail.com, MAERSK Kinloss). **2026-09-10:** full-system audit — `docs/sprint-audits/full-system-audit-2026-09-10.md`; roadmap rewritten (previous at `docs/archive/roadmap-2026-05.md`). Both P1s fixed the same day on Blake's go: prod `.env` flipped to `HYBRID_RETRIEVAL_ENABLED=false` (it had carried `true` since May against the 07-19 verdict), and the Captain's vessel set to `United States` — her four questions went from 4/32 foreign-flag hits (Unknown) to 0/32; harness 0.823/0.658. Also shipped: scheduled Celery ingest now runs through `run_ingest.sh`, the non-concurrent monthly REINDEX task is gone, `uv.lock` regenerated. **51 of 56 vessel profiles have flag Unknown** — the product fix (roadmap item 6) is next. Corpus is 106,041 chunks / 66 sources.
- **2026-09-22 Opus 5.5 rollout (`claude-opus-5-5`, $4/$20 vs 4.8's $5/$25):** `MODEL_MAP[3]` + `REGENERATION_MODEL` moved from Opus 4.8; `_MODEL_ALIAS` gained the key (4.8 kept, D6.73 rule). Opus 5.5 always thinks and opens every response with a `thinking` block — the regeneration path's `response.content[0].text` would have raised on it and silently disabled regeneration (swallowed by the D6.96 bare except). `engine._text_of()` now reads by block type; `_opus_kwargs()` sends explicit effort (`medium` stream / `high` regen) + a 16K cap for Opus only (Haiku rejects `output_config`); the streaming path logs non-`end_turn` stop reasons and routes a classifier `refusal` to the GPT-4o fallback. Deployed `83ded7a`. Prod smoke on the Captain's profile: regen ok (11 s), followup turn on Opus 5.5 with 8 cites — **synthesis TTFT 12.9 s at `medium` vs 7.6 s at `low`** (2.8K vs 2.0K output tokens, same answer); `low` recommended for the streamed path, Blake's call. **LLM surface audit** at `docs/sprint-audits/llm-surface-audit-2026-09-22.md`: models are current, call shapes are not — no prompt caching on a ~10K-token static system prompt, JSON scraped instead of structured outputs, 5.7 sequential API calls per question, SDK 0.86 vs 1.8. Ranked upgrades U1–U11 there and in the roadmap.
- **2026-09-22 U1–U9 shipped** (Blake: "greenlight all recommended items"; `f64bbfc`, `cb7cf27`, `25eabf5`, `27c32a8`): SDK 1.8 everywhere; shared `packages/rag/rag/llm.py` (`text_of`, `create_json`, `cached_system`, `pdf_document_block`); structured outputs on 18 call sites, all schemas validated live (the API rejects >~20 union-typed params — `apps/api/tests` caps it at 8); prompt caching on synthesis + regen (prefix is **14.5K tokens**; hits verified); router ∥ retrieval (~0.6 s — judge→oracle is dependent, retrieval was already concurrent); native PDF input for credentials/documents; Batch-API enrichment (opt-in `--enrich` only; a batch took 35 min); OCR on Opus 5.5 `low`; Opus stream effort → `low`. **U6 (web_search_20260209) measured and dropped.** Harness after deploy: dense 0.823/0.688, first `dense-prod` baseline **0.919/0.737**. Sonnet 5's adaptive thinking on real synthesis requests (24–31 s to first token) was resolved the next day (below). SSH from Blake's laptop gets dropped upstream after bursts of connections (VPS firewall/sshd verified permissive) — batch remote work into one connection.
- **2026-09-23 Opus 5.5 is the default answer model** (Blake: "make Opus 5.5 the default … greenlight all recommended"; `3a5e9b6`, `f51cdbe`, `5f0ebb5`). **New harness `scripts/compare_synthesis_models.py`:** it captures each question's exact synthesis request from the real engine and replays it under six model/effort configs, with two blind judges (Opus 5.5 + GPT-4o). On 16 questions (14 gold + the Captain's 2), Opus 5.5 `low` beat what routing sent (10/16 Haiku): judges 8.62 vs 5.06 and 9.25 vs 8.31, flagged errors 9 vs 53, p90 first token 7.9 vs 16.4 s after retrieval, ~$0.13 vs ~$0.04 per answer cold. `medium` bought nothing for 2× first-token time. **`SYNTHESIS_MODEL_FLOOR`** (default `claude-opus-5-5`, empty = pure routing) lifts the router's pick at the synthesis call; the router remains the off-topic gate. Sonnet streams at effort `low` when it answers. Sonnet 5 JSON routes got thinking headroom: co-pilots `_REASONING_MAX_TOKENS=8000` (vessel-analysis used 96% of its old 3,000 cap), web fallback 2048 → 8192. 0 refusals on 8 sensitive-but-legit questions. **Any change to the synthesis model, effort or prompt re-runs the harness first.** Retrieval (8–19 s) is now the latency long pole → DB headroom decision. Evidence: audit §5, `data/eval/model_compare/`.
- **2026-09-23 (later) quiz generation → Sonnet 5, effort pinned `high`, cap 16K** (Blake's go on U10). Answer keys were already equal to Haiku's (95% vs 95–97%, Opus-audited); resolvable citations rose from 50% to 97%. Also fixed: the quiz/guide citation verifier was case-sensitive, so every COLREGs quiz showed 0% verified (corpus "COLREGS Rule 13" vs cited "COLREGs Rule 13(b)"). Audit §6.
- **2026-09-24 Postgres `shared_buffers` 128 → 512 MB + `pg_prewarm` autoprewarm SHIPPED** (Blake's go; `e066078`). It is set in `infra/docker-compose.yml` `command:` and applied by recreating the container (`cd /opt/RegKnots/infra && docker compose up -d --no-deps postgres`, API/worker stopped first). API downtime was 14 s. Dense harness identical (0.8226/0.6881). Warm group queries read 0 MB from outside the pool; the first question after a deploy is now about as fast as warm (DB phase 8.3 vs 7.6 s; was ~13 s). **The warm retrieval step did NOT get faster (8–11 s):** the 124-query fan-out (4 reformulations × 31 groups) is CPU- and connection-bound on 2 cores. Batching the small exact-scan groups was then measured and NOT shipped: identical results, but slower under real concurrency. Details, the corrected projection and the one-week hit-ratio baseline: spec §0.
- **2026-09-25 question audit + retrieval fixes** (`18fb15f` rag, `505bde8` study; deployed 2026-09-26 in `78a7485` with `6976759` next 15.5.26). Audited the Captain's SOLAS III/20 pair and Karynn's bunker-CLC question: `docs/sprint-audits/question-audit-2026-09-25.md`.
  - **SOLAS regulation citations resolve to the exact section.** "Chapter III, Part B, Section I, Regulation 20" retrieved 0 of Reg.20's 5 chunks; the candidate returns 5 of 8.
  - **CFR citations resolve to the section or part.** A part number used to substring-match any chunk containing the digits.
  - **The vessel-applicability filter is Title 46 only.** Its 46 CFR part lists were dropping 5,137 chunks of 33/49 CFR for containerships: Inland Rules, 33 CFR 165/169, COFR, 49 CFR 176. "33 CFR 138 COFR" went from 0 to 4 of 8.
  - Reformulation retrievals start when the rewrite returns. Dropping identifier search on reformulations was tried and **reverted on 2026-09-26** (it cost 4 of 71 pairs on the full pipeline).
  - Also: reranker `[index, score]` pairs; group skip; `jurisdiction_focus` fallback for flag-Unknown vessels; quiz exam-bank vector retrieval.
  - Harness 0.8226/0.6795 vs baseline 0.8226/0.6881: 0 pairs gained or lost, two down one rank.
  - The iterative HNSW scan stays OFF on the group fan-out (+1 pair, −0.027 MRR from 49 CFR 391 trucking rules).
  - Found in this audit and handled on 2026-09-26 (next entry): stale SOLAS rows and the parser bug behind them, cfr_49 carrying all of Title 49, and the hedge judge's `verified_citations` gate counting *retrieved* sections.
- **2026-09-26 follow-up (Blake: "Greenlight all recommended") and an incident.** Details: audit doc §6.
  - **Deployed:** `78a7485` and `2469c73`.
  - **The Captain's two questions, re-run on prod:** Reg.20 fully retrieved; the answers now give the inspection intervals.
  - **Gold set +7 questions / 9 pairs** (A25-*: citations, COFR, Inland Rules, 49 CFR 176). Dense arm, pre-audit vs deployed: 0.7606/0.6337 → 0.8451/0.7178.
  - **SOLAS root cause was the parser**, which cut "Chapter II-1" at the first hyphen. Fixed in `825c62e`.
  - **New `ingest/prune.py`** (`--stale-report` / `--prune-stale` / `--prune`): refused unless provably safe; removed rows copied to `data/pruned/*.csv.gz`.
  - **`ingest/cfr_scope.py`:** cfr_49 now ingests maritime parts only.
  - **Applied:** SOLAS 1,739 → 848 and cfr_49 15,967 → 3,145 chunks; the corpus is now **92,336**. Dense harness after the cleanup: recall 0.8592 (+0.014), MRR 0.6924 (−0.025, three fire-equipment pairs whose #1 had been a stale short row).
  - **Re-measured on the clean corpus:** the within-chapter SOLAS search and the group iterative scan both stay OFF. 8 of 8 chapter-cited questions already hit without the chapter search, and the iterative scan gains +0.005 MRR for +100 ms.
  - **Engine `51231cc` verified on prod and deployed.** The recovery-gate fix: the corpus oracle now runs on a cited `partial_miss` and surfaced a verified quote in testing. Analytics moved after `done`: last token → `done` went 3.7 → 0.0 s on a normal answer and 9.3 → 4.4 s on a hedged one. Credential reminders appear only on credential questions.
  - **Full pipeline on the clean corpus** (71 pairs): pre-audit 0.8732 / 0.6722 → shipped **1.0000 / 0.7301**.
  - **New baselines:** dense 0.8592 / 0.6924, dense-prod 1.0000 / 0.7301.
  - **INCIDENT: Anthropic credits exhausted from 00:15 to ~02:10 UTC 2026-09-26.** Every Claude call returned 400, and the GPT-4o fallback served (10.6 s, not streamed; messages persisted). No user traffic during the outage. `eval_retrieval.py` `-prod` arms now refuse to run without the API.

- **2026-09-26 (later; no Anthropic spend, per Blake's new rule under Operating norms).**
  - **Stripe** (`4f19025`): the webhook endpoint is subscribed to 8 events, but **not** `customer.subscription.created` or `.deleted` (read via the API).
    - First purchases never recorded `billing_interval`. Checkout and invoice.paid now read it off the subscription, and the ledger takes it from the subscription too.
    - Ended subscriptions never downgraded. The new daily Celery task `reconcile_subscriptions` (12:30 UTC) re-syncs any paid row whose period ended more than 2 days ago. It fixed the `kdmarchal+test` zombie (Stripe: canceled 05-08) on its first run.
    - Intervals were backfilled from Stripe: the Captain → month, Karynn's comped pro → year.
    - **Blake:** add the two events in the Stripe dashboard so downgrades are immediate.
    - The Captain's **$39.00 charge** is a mapped price: `STRIPE_PRICE_CAPTAIN_MONTHLY` is the legacy Pro price id. Every page advertises $39.99, and the support FAQ still describes the old Pro plan. Blake decides which way to align.
  - **CI** (`.github/workflows/tests.yml`, green from `fafc353`): the api, rag and ingest unit suites run on push to main and on PRs. No secrets and no paid APIs.
  - **Sentry** `environment` tag on web client and server (`6ab370d`).
  - **Ingest fixes** (`320e123`):
    - IMO-code sources (`marpol_amend`, `stcw_amend`, `imo_mepc`, `imo_msc`) now keep their real source name in the pipeline. Hash dedup, the safeguard and prune had been looking at an empty source.
    - The prune tool never removes `(manual)` rows. Other `manual_add` rows still show as stale and must be reviewed out of the report.
  - **More stale rows pruned** (backups in `data/pruned/`):

    | source | pruned | what |
    |---|---|---|
    | `marpol_amend` | 311 | 05-01 resolution-level duplicates of the per-regulation rows |
    | `stcw_amend` | 14 | same pattern |
    | `cfr_46` | 52 | 46 CFR 298, gone from eCFR |
    | `cfr_33` | 68 | mostly expired temporary rules, e.g. 165.T01-0903 |

    Corpus is now **91,892**. Dense harness: recall unchanged; one ERG tie flipped.
  - **Deliberately not pruned** (both fixed the same evening; next entry):
    - `imdg`: 30 manual rows, and 3 duplicate keys in its parse.
    - `marpol`: 131 one-chunk per-regulation rows are the only per-regulation MARPOL layer. The fix is per-regulation splitting in the MARPOL parser.
- **2026-09-26 (evening; Blake: "Greenlight all"; no Anthropic spend).** Deployed `aaa6c3a`, `af7089f`, `7c4795d`. Evidence: audit doc §7.
  - **MARPOL is split into regulations** (`aaa6c3a`). The adapter now emits one section per regulation: 140 across Annexes I–VI, e.g. "MARPOL Annex VI Reg.14".
    - They replace 250 chapter-level rows and the 131 D6.88 one-chunk rows. D6.88 had read page running heads as headings and filed 12A's text under Reg.12.
    - Five anchored fixes repair OCR damage. Annex I Reg.10, Annex I Reg.26 and Annex VI Reg.13 (NOx) open where their text resumes, with a note that the start is missing. Out-of-order Reg.27 and Reg.28 pages go back behind their headings. Without the fixes, the NOx text would sit under Reg.12 (ODS).
    - A misfiled P&A Manual page moves to Annex II App.IV.
    - Re-ingested with the new `--enrich-cache-only` flag (no API calls): 610 rows (288 regulation, 322 appendix / UI / articles). 251 pruned (backup `data/pruned/marpol-20260926-171700.csv.gz`).
    - The 121 appendix / UI rows kept their aliases. The 288 regulation chunks are plain. Re-enriching them is one Batch-API run, under $1. Not run (spend rule).
  - **Scan gaps (Karynn can re-capture the pages):**
    - Annex VI Regs 11, 19 and 20 are absent from the scan.
    - The opening pages of Annex I Regs 10 and 26 and of Annex VI Reg 13 are absent.
  - **MARPOL citations resolve to the regulation** (`af7089f`).
    - Before: "MARPOL Annex VI Regulation 14" became substring searches for "Annex VI" and "Regulation 14" over every source. That put 10 rows, in storage order, above every vector hit.
    - Now a cited regulation is an exact-section identifier.
    - An annex named without a regulation returns that annex's 5 chunks nearest the query. On 2ndmate09's "annex V exemptions" question, removing it leaves zero Annex V text in the top 8.
    - The bare "Annex I Regulation 22" form counts only when no other instrument is named, because the Load Line Convention's Annex I numbers regulations too.
  - **Dense harness, 79 pairs (71 + A26-1..7):**

    | run | strong recall@8 | MRR |
    |---|---|---|
    | before | 0.8354 | 0.6755 |
    | + corpus | 0.8608 | 0.6793 |
    | + retriever | 0.8608 | **0.7046** |

    The corpus change gains Reg.14 and Reg.12A. The retriever change moves four cited pairs from rank 2 to rank 1. No pair was lost. **New dense baseline: 0.8608 / 0.7046.** `dense-prod` was not re-run (spend rule).
  - **IMDG** (`aaa6c3a`): the duplicate "Foreword" and "Part 3" headers now merge instead of overwriting, so the Vol.1 foreword's opening is back.
    - Re-ingested fresh, no prune; the 551 sub-clause rows and 30 manual rows are kept.
    - `merge_duplicate_sections` now lives in `ingest.models` (SOLAS, MARPOL and IMDG use it).
  - **Vessel flag** (`7c4795d`). `create_vessel` hard-coded `flag_state = 'Unknown'`, and neither create nor update accepted a flag. That is why 51 of 56 vessels are Unknown.
    - The API now takes and returns `flag_state`.
    - Chat shows a one-click "confirm your flag" banner while the active vessel's flag is Unknown. The suggested flag comes from `jurisdiction_focus`.
    - The vessel editor has a Flag field.
    - IMO-number enrichment (roadmap item 6) remains.
  - Corpus **91,801**.
See `docs/PROJECT_STATE.md` for a fuller operational snapshot and `docs/roadmap.md` for the prioritized backlog.


## Known issues (2026-05-08)

The audit caught two memory items as **stale** — both are actually resolved:

- **Vocab mismatch** (memory said: "no fix yet"): SHIPPED. `packages/rag/rag/synonyms.py` has lifejacket→lifesaving-appliance, log→logbook, mob, stability, stencil/stenciled/stenciling. `packages/rag/rag/query_rewrite.py` produces 2-3 reformulations every chat (default ON). Two intent expanders fire on dual-signal gates.
- **`ism_supplement` migration drift** (memory said: "added live, not in migration files"): RESOLVED. Migration `0090_add_nmc_exam_bank_source.py` defines the canonical source list including `ism_supplement`.

Status re-verified 2026-07-18 (Fable full audit):

- ~~JWT signing key~~ — **FIXED.** `.env` now uses `REGKNOTS_JWT_SECRET_KEY` (matches `env_prefix="REGKNOTS_"`); runtime-verified not the dev default (64-char secret).
- ~~`.env` permissions~~ — **FIXED.** 600.
- ~~Zero DB backups~~ — **FIXED (2026-07-19).** Nightly pg_dump + **restore-verified** (runbook `docs/runbooks/db-restore.md`) + staleness gates in smoke.sh and the weekly maintenance unit. Offsite sync scaffolded and installed; **only Blake's DO Spaces bucket+keys step remains** (5 min; header of `scripts/backup_offsite.sh`).
- ~~refresh-weekly dead~~ — **FIXED in May, then deliberately DISABLED 2026-08-10** (Blake: 'questions only' cost posture). Only `regknots-backup.timer` and `regknots-db-maintenance.timer` remain enabled. Celery Beat still refreshes `cfr_*` + `nvic` weekly — see 'Two schedulers' above and the 2026-09-10 audit.
- ~~No retrieval eval gate~~ — **FIXED (2026-07-19).** `scripts/eval_retrieval.py`; 124 unit tests green; baseline to beat: strong-recall@8 0.790 / MRR 0.627.
- ~~LLM-helper boilerplate copy-pasted 6× in `me.py`~~ — **FIXED 2026-09-22** (`packages/rag/rag/llm.py` `create_json` + structured outputs).
- Dense retrieval's own 13/62 missed gold pairs = the next tuning target (per-pair dumps in `data/eval/retrieval/`).

Full audit report (models, retrieval, UX, product packaging): see the 2026-07-18 session; actionable items queued as tasks (paywalled-data acquisition, offsite backups, eval harness + hybrid flip, fleet audit-readiness, citation trust UX pack).

## Pointers

- **Operational state:** `docs/PROJECT_STATE.md`
- **Strategic roadmap:** `docs/roadmap.md`
- **Latest full audit:** `docs/sprint-audits/full-system-audit-2026-09-10.md`
- **LLM surface audit (call sites, caching, structured outputs, SDK):** `docs/sprint-audits/llm-surface-audit-2026-09-22.md`
- **Corpus inventory:** `docs/corpus-status.md`
- **Scaling thresholds:** `docs/scaling-roadmap.md`
- **Cowork tasks:** `docs/cowork-task-prompts.md`
- **Long-form bring-up (deeper):** `docs/chat-bring-up-prompt.md`

---

*Last updated 2026-09-26 evening (MARPOL per regulation + citations, IMDG duplicate headers, vessel flag prompt; earlier: question-audit follow-up, SOLAS / cfr_49 cleanup, Anthropic credits exhausted). When this drifts from reality, fix it — that's the rule.*

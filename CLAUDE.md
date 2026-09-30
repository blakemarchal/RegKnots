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
- 2026-05-09 D6.84 Sprint A: confidence tier router shipped in **shadow mode** on prod. Adds 4-tier provenance (✓ Verified / ⚓ Industry Standard / 🌐 Relaxed Web / ⚠ Best-effort) on top of today's pipeline. Closes the partial_miss-low-web dead zone where Jordan Dusek's gasket-class questions hedged. Flag: `CONFIDENCE_TIERS_MODE=off|shadow|live`. Migration 0093 adds `tier_router_shadow_log` table + `messages.tier_metadata` JSONB. The router was killed on 2026-05-19 (`docs/sprint-audits/tier-router-shadow-kill-2026-05-19.md`; admin view and endpoints removed in `af71074`). 12/12 unit tests pass. Gold set at `data/eval/tier_router_gold.json`. **Phase E flip to `live` is operator-driven.**
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
  - **Hybrid verdict — DO NOT FLIP.** New `scripts/eval_retrieval.py` (retrieval-only recall@k/MRR, imports the eval_rag_baseline gold set). Dense 0.790 strong-recall@8 / 0.627 MRR vs hybrid RRF 0.548 / 0.416 — hybrid loses 16 pairs, gains 1 (lexical lane vetoes dense's correct hits via rank-blind RRF). ⛔ MEASURED comment on the config flag; evidence in `data/eval/retrieval/`; verdict doc `docs/hybrid-retrieval-verdict-2026-07-19.md`. ef_search 100 "measured zero effect" — invalid test (asyncpg RESET ALL wiped the pool-init SET; correction in the verdict doc, 2026-09-24). **Any retrieval change now runs this harness first.** Baselines to beat: **dense 0.8608/0.7168** (79-pair gold set, 2026-09-27 after the NVIC 06-72 fix; 0.7046 on 09-26 after the MARPOL split); **dense-prod 1.0000/0.7301** (71-pair set, 2026-09-26; not re-run on 79). The `dense` arm does not exercise query rewrite, reformulations or the reranker; a change to those must be measured with `--arm dense-prod`. A reformulation change shipped on dense-only probes on 2026-09-25 and was reverted the next day (−4 pairs on dense-prod). (The 2026-09-10 re-run gave 0.823/0.658, after prod was flipped back to dense; it had been serving hybrid since May against this verdict.)
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
- **2026-09-27 (Blake: "all 4 in order"; Karynn approves; "free before any new spend").**
  - **Usage (read-only SQL, 2026-09-26):** 64 external users; 40 ever asked a question; **1 active in the last 30 days** (the Captain). Signups by month: Apr 36, May 22, Jun 4, Jul 1, Aug 1, Sep 0. No source recorded for anyone. Distribution is the bottleneck, not answer quality.
  - **Signup attribution** (`4abf1a6`, migration **0116**): `users.signup_source` + `users.signup_attribution` record the first campaign touch (utm_*, `?src=` outreach code, `?ref=`, referrer, landing page).
    - Deliberately **not** `referral_source`, which drives the tithe split and grants promo pricing.
    - The `/` → `/landing` redirect used to drop the query string; it now keeps it.
    - Admin: signup source on each user, and a "Signups by source" card on the Traffic page.
  - **Model-led grounding ON** (`7ed5364`): Opus may answer from its own knowledge where the excerpts are incomplete, marked as not in the retrieved excerpts (`rag.prompts.MODEL_LED_GROUNDING`).
    - `compare_synthesis_models --prompt-ab`, 18 questions, $3.66: judges 7.94 → 8.61 (Opus) and 9.44 → 9.67 (GPT-4o); accuracy flat; errors flagged 17 → 15; first token +1.7 s.
    - Flag `MODEL_LED_GROUNDING_ENABLED`, default on. Precision Mode users keep the strict posture. Audit doc §8.
  - **Outreach v1 (free) staged** (`9ea3964`): spec `docs/specs/outreach-agent-2026-09-27.md`.
    - Leads: 705 towing operators from the public-domain Army Corps 2017 operator file (`scripts/outreach/build_leads.py` → `data/outreach/leads.csv`, gitignored).
    - Six Subchapter M hooks checked against the corpus.
    - A draft-only Claude desktop scheduled task: Gmail drafts, Blake sends.
    - Waiting on Blake: sending account, postal address, offer.
  - **Outreach LIVE** (`7f26670`): Claude desktop scheduled task `regknots-outreach`, weekdays 06:38 local, running on Blake's laptop while the app is open.
    - It writes Gmail drafts into the account the Gmail connector uses (blake@regknots.com once Blake switches it from blakemarchal@gmail.com) and never sends: 5 a day through 2026-10-02 while the new mailbox warms up, then 10. The signature carries hello@regknots.com and 20 N Sandpiper St, La Marque, TX 77568.
    - The offer is the existing 30-day fleet (Wheelhouse) trial, no card. Prod has `CREW_TIER_ENABLED=true` and `CREW_TIER_INTERNAL_ONLY=false`.
    - The link is `/register?next=/workspaces&src=ob-NNNN&utm_...`. `?next=` now survives AuthGuard → login → register; before, a new signup always landed in chat and never saw workspace creation.
    - **2026-09-28: drafts are saved by `scripts/outreach/gmail_draft.py`, never the Gmail connector.** The connector rewrites every link it saves into `google.com/url?q=…`, and clicking one opens Google's "Redirect Notice" page. The script uses the Gmail API (Google Cloud project `regknots-outreach`, Internal consent, scopes `gmail.compose` + `gmail.metadata`, OAuth client and token in `~/.regknots/`). It renders one branded template: logo signature, the brand name **RegKnot** (as on the site and logo), and the short link `regknots.com/fleet?src=ob-NNNN` (a 307 in `apps/web/next.config.ts` to the fleet-trial signup with the utm tags).
  - **2026-09-28: Sonnet 5 → Sonnet 5.5; one setting for the small model** (Blake: "Greenlight 1 and 3"; the answer-model comparison was declined).
    - Every Sonnet call site now uses `claude-sonnet-5-5` (same $2/$10): co-pilots, quizzes (effort `high` kept), deep study guide, PSC checklists, credential and document extraction, web fallback, oracle synthesis, the image upgrade, the router's off-topic confirmation and the ingest enricher (effort `low`, cap 1,024). **Answers stay on Opus 5.5 `low`** (`SYNTHESIS_MODEL_FLOOR`).
    - Sonnet 5.5 calls carry the server-side refusal fallback (`rag.llm.messages_create`: beta `server-side-fallback-2026-07-01`, `fallbacks="default"`); the Batches API rejects it, so the enricher's batch path sends none.
    - **The router classifier returns a structured `{"score": 0-3}`.** Sonnet 5.5 answered "Return ONE digit" with prose, and the old regex took the first 0-3 anywhere in the reply. Its 10-token cap also meant any thinking on Sonnet left the confirmation with no text, which the gate treats as "allow".
    - `rag.llm.SIDECAR_MODEL` (env `SIDECAR_MODEL`, default Haiku 4.5) is the one small model: router, distill, rewrite, rerank, hedge judge, citation oracle, hedge audit, titles, support bot, fast study guide; ingest's bulletin classifier reads the same env var. `small_call_kwargs()` keeps Haiku 4.5's caps and gives a model that thinks by default headroom and effort `low`.
    - `chat._model_alias()` falls back to the model family, so a new Haiku / Sonnet / Opus ID is stored as its alias instead of NULL (the D6.73 failure).
    - Live on the prod key (~$0.12): structured output + fallback OK; router scores identical on Haiku 4.5 and Sonnet 5.5 (5 of 5, Karynn's hazmat fire scenario = 3); the 8 sensitive questions (IMDG 6.2, IHR, cholera, D-2, phosphine, HCN, H2S, 33 CFR 101) got 0 refusals; enricher 12 terms at effort `low`.
    - **Haiku 5.5 (due the week of 2026-10-05):** set `SIDECAR_MODEL`, then measure the dense-prod harness arm, the hedge judge's gold set and latency. First check whether it accepts `effort` (`small_call_kwargs` sends it to any non-4.5 model) and update the HAIKU price row in `scripts/compare_synthesis_models.py`.
  - **Email: Google Workspace since 2026-09-27** (Business Starter, flexible plan, **one** license at $8.40/mo; paid service starts 2026-10-11).
    - `blake@regknots.com` is the only user and the admin. `hello@` and `support@` are its aliases. `captain@` is a Google Group whose member is Karynn's Gmail; outside senders may post to it.
    - DNS (Namecheap): MX `smtp.google.com` (ImprovMX removed), root DKIM `google._domainkey` (authenticating), DMARC `p=none` with reports to blake@. SPF was already `include:_spf.google.com include:amazonses.com`.
    - Resend stays transactional only, on `mail.regknots.com` (`send.mail` MX + SPF, `resend._domainkey.mail`, `_dmarc.mail`, all untouched), and must never carry cold email.
    - Any address other than blake@, hello@, support@ and captain@ now bounces. There is no catch-all.
  - **Company documents SHIPPED** (`baf500f`, migration **0117**): a fleet's SMS / TSMS manuals in workspace chat.
    - Tables `workspace_documents` + `workspace_document_chunks`, never `regulations`, every read filtered by workspace_id.
    - Local extraction (pypdf / python-docx); Celery `process_company_document`; the engine's `company_context` callback folds a COMPANY DOCUMENTS block into `context_str`.
    - `[Company: title §section]` chips resolve via `/workspaces/{id}/documents/citation`.
    - Prod smoke test on an archived workspace: processed, retrieved, looked up, isolated from other workspaces, cleaned up. Spec: `docs/specs/company-documents-2026-09-27.md`.
  - MARPOL chip regex now keeps letter suffixes ("Regulation 12A" → Reg.12A).
  - **NVIC 06-72 CO2 figure FIXED** (`cda8a87`, deployed as `8330814`). "Discharge of 35% of the required quantity of CO2 … within two minutes" is printed in USCG's own PDF of NVIC 6-72, a retype of the 1972 circular that kept the scanner's misreads. Our OCR never touched it: this NVIC goes through the pdfplumber adapter. 46 CFR 34.15-5, 76.15-5 and 95.15-5 require at least 85 percent within 2 minutes.
    - `ingest/sources/nvic_fixes.py`: anchored fixes applied to the extracted text before the section split, so the Sunday `nvic --update` keeps them. An anchor not found exactly once is logged and skipped.
    - 37 fixes for 06-72:
      - the 85% figure;
      - "213" for 2/3;
      - a 5/8-inch sprinkler that the guide's own K-factor makes 3/8;
      - a deck foam rate of 0.16 for 0.016 gpm/ft²;
      - 23 temperatures whose degree sign became a trailing 0 ("l300F" is 130°F);
      - footnote numbers run into figures.
    - The three plausible-looking wrong figures (35%, 0.16, 5/8") carry a `[corrected: …]` note.
    - `ingest.cli --source nvic --nvic 06-72` re-ingests one NVIC from the files on disk: no discovery, fresh mode, implies `--no-notify`.
    - Re-ingested on prod: 38 rows written, the exact set a local parse predicted (that parse reproduces prod's hashes). 32 rows carry fixes; 6 are collision flip-backs (next item). Backup `data/pruned/nvic-06-72-before-textfix-20260927-140953.csv.gz`.
    - Dense harness: 0.8608 / 0.7105 before, **0.8608 / 0.7168** after, no pair gained or lost. Weak recall 0.9114 both runs; the 09-26 run had 0.9241, so that dip predates the fix.
    - **Found, spawned as a task:** NVIC section numbers collide, because numbered lists inside enclosures restart at "1.". The Sunday run parsed 6,805 chunks for 4,202 rows. It re-embeds about 3,500 chunks a week and flips the colliding rows; the bulk gate suppresses the notification.
    - Same misread signatures, not reviewed: NVIC 03-06, 11-84, 03-94, 02-88, 05-87 and 08-87 (degree as 0); 11-63 and 11-82 (letter in a figure). 10 rows in all.
- **2026-09-29 video ads, first cut** (Blake: "greenlight the video … a mix of real content and your 'flare'"). Script: `docs/marketing/video-script-2026-09-27.md`; the shared copy for Karynn is the Claude Doc "RegKnot video script".
  - Main 45 s plus two 15 s towing cuts ("First trip", "Audit coming"), each 9:16 and 16:9, with covers. The masters are in `data/video/out/final/` (gitignored).
  - Built from real captures of the live app on the M/V Bay Pioneer demo profile, marked "Real answer · sped up", plus motion graphics. There is no stock footage, and the score and sound effects are synthesized.
  - Pipeline in `scripts/video/` (README). Every frame is `seek(t)` in a Chrome page, rendered through puppeteer-core into ffmpeg. `audio.py` syncs to the stage's event log.
  - Claims on screen were checked against the eCFR text of 46 CFR 140.410, 140.515(c) and 140.915(a).
  - Karynn's lines are on screen as captions. Her voice memo is still to come (she was recording on 2026-09-29); the README covers how it drops in.
  - Temp AI narration versions (`fc13d63`): stock OpenAI voices, female `marin` and male `cedar`, never her voice. Her line 6 is read in the third person ("Built by Captain Karynn Marchal…"), and the end card says "Narration: AI voice". They are in `data/video/out/share/`. TTS runs where the prod OpenAI key is (the local key is stale). Whisper transcribed every finished mix word for word over the music.
  - Found in the footage and spawned as a task: CFR chips drop the opening "(" and leave "(b))" (`apps/web/src/lib/parseMessage.ts` `CFR_RE`).
- **2026-09-29 CFR paragraph chips fixed** (the footage bug above). "(46 CFR 140.410(b))" rendered as "[46 CFR 140.410](b))": the chip pattern's optional "(" took the opening parenthesis, and its optional ")" met the "(" of "(b)".
  - The chip label keeps the paragraph (`46 CFR 140.410(b)(1)`, `46 CFR 140.910(c)–(d)`) and still opens 46 CFR 140.410. Parentheses go into a chip only as a pair around the whole citation. The footer still lists sections.
  - The live scanner (patterns, `scanCitations`, `extractFooterCitations`) moved from `ChatMessage.tsx` to `apps/web/src/lib/parseMessage.ts`. The `parseContent()` that lived there was dead code.
  - First web unit tests: `pnpm test` in apps/web (node:test with type stripping, Node 22.6+, nothing to install). CI runs them in a new `web` job.
  - **Deployed 2026-09-29 in `fc13d63`** (smoke OK; the production chunk carries the new paragraph pattern).
  - The video footage was captured before this fix and still shows the stray "(b))". Re-capturing the affected shots waits until Karynn's voice-over is in (Blake: hold off). It needs no new questions, only the existing M/V Bay Pioneer conversations reopened.
- **2026-09-29 admin redesign + customer UX pass** (Blake: "full greenlight to go with recommended"; `ccdf2e5` api, `5057cdd` admin, `58c8f1a` web). **Deployed 2026-09-29 in `7e91744`** with the follow-up below.
  - **Admin layout** (`apps/web/src/app/admin/layout.tsx`, `_components/AdminShell.tsx`): a sidebar in five groups (Overview / Customers / Answers / Support / Platform) with live counts, a phone drawer, the "real users only" switch in one place, and `admin/error.tsx`, so a page crash keeps the sidebar. Shared bits are in `_lib/` (AdminContext, types, format) and `_components/ui.tsx`.
  - **Dashboard** (`/admin`): a "needs attention" strip, KPI tiles with 26-week sparklines, a weekly signups/active/questions chart, the funnel, answer quality, top citations, questions by role, latest questions, revenue and newest signups. The data comes from the new **`GET /admin/dashboard`** (`apps/api/app/routers/admin_dashboard.py`, read-only, external users by default).
  - The old six-tab page is one page per tool now. Old `?tab=` links redirect.
  - **Admin bugs fixed:**
    - The hedge rate on the Overview was always 0%: it read `hedge_audits.classification` instead of `retrieval_misses.judge_verdict`.
    - Saving a hedge audit older than the newest 200 returned 404.
    - Web-fallback thumbs from non-admins raised AttributeError, and the web client sent them without the token.
    - The custom-email "wheelhouse" audience skipped trialing fleets.
    - Several write actions left no audit-log entry.
  - **Retired (HTTP 410):**
    - `POST /admin/reset-all-pilots`: it would wipe every customer's chats and overwrite their subscription status.
    - `POST /admin/jobs/trigger-ingest`: it spawned in a directory that does not exist and bypassed `run_ingest.sh`.
    - Web-fallback replay is owner-only.
  - **Customer side:**
    - 246 `bg-[--color-x]` classes were empty rules under Tailwind 4, so register, sign-in, onboarding, invite and password-reset buttons had no fill. A guard test is in `src/lib/tailwindClasses.test.mjs`.
    - Chat has one send path, so starter prompts and Resend get the paywall/verify/429 handling and Stop.
    - The account-page switches save on flip.
    - The trial survey no longer shows forever after a trial ends.
    - Phone form fields are 16px, so iOS stops zooming.
    - Also: local-day log dates, delete confirmations, vessel add/edit navigation, and FAQ pricing that matches `/pricing`.
  - Checked in a local browser against a mock API with synthetic data (desktop and phone, full and empty data). `next build` is clean; api 70 and web 7 tests pass.
  - **Production numbers the dashboard surfaced (read-only, 2026-09-29):** funnel 64 signed up → 40 asked → 15 came back → 1 active in 30 days → 2 paying. MRR $48.99. **165 hedge audits are open, and none has ever been triaged.**
  - **Follow-up, same day** (Blake: "Fix those found items, then push and deploy"; `92833c4` api, `7e91744` web):
    - **Self-serve account deletion.** Landing and pricing promise "Your data, your delete button"; only the owner could delete an account.
      - `POST /auth/delete-account` needs the password and the typed word DELETE. It refuses admins, and owners of a Wheelhouse other people use (transfer ownership or remove the crew first). Wrong input returns 400, not 401.
      - The account page has a "Delete account" section. The login page confirms the deletion. The privacy page says deletion is self-serve and that payment records are kept.
      - `app/account_deletion.py` is shared with the admin delete. Steps: cancel the user's and owned workspaces' Stripe subscriptions (nothing is deleted if Stripe refuses); delete owned workspaces and the user in one transaction; remove uploads inside `upload_dir`. **The admin delete used to leave Stripe billing.**
      - **Migration 0118:** `billing_events.user_id` is nullable, ON DELETE SET NULL (was CASCADE). A deleted customer's invoices stay in revenue and partner accruals. Dry-run on the prod schema before deploy. **Alembic head is 0118.**
      - **Left as is on purpose:**
        - Single conversations still only archive (the D6.80 decision; data keeps feeding retrieval work).
        - A deleted crew member's workspace conversations go with their account.
        - A deleted workspace's `workspace_billing_events` cascade with it.
    - The admin IMO/NMC checks run on a private event loop in a worker thread (`_run_task_off_loop`). Their blocking `requests.get` (30 s timeouts) used to stall the API.
    - The dashboard counts answers by model. `fallback_gpt4o` (Claude unavailable) shows in Needs attention; the retired model-usage panel was the only place it appeared.
    - `/admin/users` and `/admin/chats` "exclude internal" leave out admins too, like every other endpoint. `/admin/model-usage` reports `total_tokens`: there is one number per answer, which had been labelled output tokens.
    - `useEscapeKey` (`src/lib`): Escape closes the topmost sheet, drawer or modal, across 11 overlays.
    - Menu labels match their pages: Credentials, Help & Support, and a "Study" section with "Study Tools". `/workspaces` is titled Wheelhouse.
    - Karynn's DB row has `is_admin = true` (read-only SQL).
- **2026-09-29 corpus gap audit, inland / USCG focus** (no spend): `docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md`. **Findings, not yet fixed; the plan awaits Blake's go.**
  - The CFR is complete: 46 CFR has 8,319 of 8,321 eCFR sections, 33 CFR 4,596 of 4,598. 46 USC and the MSM volumes are complete too.
  - **NVIC discovery drops 36 current NVICs.** `nvic.py` `_find_pdf_link_in_tag` requires links to end in `.pdf`, and USCG serves them as `.pdf?ver=…`. Missing: 03-16 (towing officer credentialing and the TOARs), the STCW endorsement series 05-14 to 24-14, 01-17 to 04-17, 01-20, 01-23, 01-24, 01-26 and others.
  - **We serve cancelled medical guidance.** NVIC 04-08 comes in by hand through `_EXTRA_DOCS`; the Merchant Mariner Medical Manual (COMDTINST M16721.48) cancelled it in 2019 and isn't ingested.
  - **`uscg_bulletin` is ~90% expired operational notices** (outlooks, broadcast notices), and its newest item is dated 2026-02-03. Retrieval never reads `published_date` or `expires_date`.
  - Every non-CFR row's `regulations.title` reads "COLREGs — …" (`models.TITLE_NAMES[0]`). Nothing reads the column.
  - Unverified citations are mostly the model's section numbers, not gaps: 46 CFR 10.215 is now 10.301–10.306, and 33 CFR 83.1 means 83.01.
  - Ranked acquisitions: NMC checklists (we have 4 of 115) plus the TOARs; CG-CVC policy letters, work instructions and forms (~80); the TVNCOE Sub M package; 196 USCG Safety Alerts; VTS manuals and waterway action plans; EPA VGP / VIDA (40 CFR 139). Tier 1 embeddings cost under $1.
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

*Last updated 2026-09-29 (corpus gap audit, inland/USCG: NVIC discovery bug, cancelled medical NVIC; self-serve account deletion + migration 0118; admin redesign + /admin/dashboard, customer UX pass incl. the Tailwind button-fill bug; CFR paragraph chips fixed, first web unit tests; video ads first cut; earlier: NVIC 06-72 misread figures fixed; company documents shipped, outreach live; signup attribution, model-led grounding on). When this drifts from reality, fix it — that's the rule.*

# RegKnots Roadmap

**Last updated:** 2026-05-09 (post-D6.83 audit + remediation sprint)

This is the strategic shipped/in-flight/upcoming view of the product. It's separate from `docs/PROJECT_STATE.md` (operational one-pager — alembic head, current corpus, hot-button bugs) and `docs/scaling-roadmap.md` (capacity thresholds and what each one triggers). Findings, calibration, and the prioritized 30-day list lift directly from `docs/sprint-audits/full-system-audit-2026-05-08.md`. The previous version is archived at `docs/archive/roadmap-2026-04.md`.

---

## Recent shipped (last 14 days)

Working backwards through `git log --since="2026-04-22"`. Sprint numbers are the ones in commits, not invented.

- **Post-D6.83 audit remediation** (2026-05-08 → 2026-05-09, commits `b2efe1f` → `5d2c567`). End-to-end execution of the 2026-05-08 full-system audit's critical-and-high items in one sitting. JWT secret rotated (env var name fix); `.env` mode 600; daily Postgres backup via `regknots-backup.timer` with `pigz -3` + corruption checks (`scripts/backup_postgres.sh`); systemd `MemoryHigh`/`MemoryMax` cgroup drop-ins on api/web/worker (no more global-OOM blast radius); 2 GB swap; `scripts/run_ingest.sh` wrapper for transient-cgroup-isolated ingest; exec bit fixed in git for all 4 shell scripts (refresh-weekly came back to life as a side effect); `HYBRID_RETRIEVAL_ENABLED=true`; new `packages/rag/rag/maritime_glossary.py` with 52 confidence-tagged slang→formal entries (fire wire → emergency towing-off pennant, etc.); query rewriter prompt now opens with maritime-slang priming + 9 worked examples + 25-entry quick-reference table; citation verifier handles CFR parent-range references and IMO-family MSC.X(Y) sources (closes 6+ false-negative F's from the regression eval); UptimeRobot setup runbook at `docs/runbook-uptimerobot.md`. README.md and CLAUDE.md created at repo root (both were missing). PROJECT_STATE.md and roadmap.md refreshed against verified live numbers.
- **D6.83 Study Tools — Sprint A1-A5 + Sprint B `/education`** (2026-05-04 → 2026-05-07). Curated `nmc_exam_bank` ingest adapter, backend router with monthly cap accounting, `/study` page with quiz + guide flows, take-the-quiz interactive surface, content_md rendered as actual markdown, then bug fixes and the `/education` landing page. Account toggle to hide Quizzes & Guides from nav (e66a731), with toggle propagation fixed without refresh (519bdce).
- **`scripts/deploy.sh` + `scripts/smoke.sh`** (2026-05-07, 107ee6a). Boring deploys: `git fetch && git reset --hard origin/main && systemctl restart …`, three-stage smoke (HTTP 200, route bundle in HTML, canary string in JS chunk). Closes the ssh-and-edit drift the old roadmap §1f had as open.
- **D6.82 Sprint C** — moved 4 AI Co-Pilots from Captain to Mate in marketing copy.
- **D6.81** — unified role/persona to one source of truth across web + api.
- **D6.80** — soft-archive for conversations + mobile-compact EmptyState.
- **D6.79** — auto-populate vessel selector when opening chat from history.
- **D6.77** — morning UX polish from Karynn's testing list.
- **D6.76** — declare 35 triaged NMC PDFs from cron-discovered backlog; dedupe `/landing` inline marketing copy via shared module.
- **D6.75** — weekly NMC corpus refresh via systemd timer; 5 new NMC announcement PDFs into `nmc_policy`; `_MAX_TOKENS` bumped 2048 → 8192 to fix Karynn's Opus truncation; classifier tightened so "tell me about X" routes to Sonnet not Opus.
- **D6.74** — chat "keeps stopping mid stream" UX gap fix.
- **D6.73** — off-topic gate Sonnet confirmation + missing Opus alias.
- **D6.72** — wow-factor marketing parity sections on every entry point.
- **D6.71 Sprint 7a — hybrid BM25 + dense retrieval** (foundation, dark-launched behind `HYBRID_RETRIEVAL_ENABLED=False`). Frequency-filter on the lexical tsquery.
- **D6.70 Sprint 8 — citation oracle** (Layer-2 retrieval intervention).
- **D6.69** — Subchapter M / TSMS source affinity (Bay Pioneer miss fix).
- **D6.68 Stage 1** — token-by-token streaming on the chat path.
- **D6.67** — expanded credential types + smarter scanner prompt.
- **D6.66 Sprint 5** — multi-query rewrite + Haiku reranker + title-boost.
- **D6.65** — stencil synonyms + equipment-marking intent expander.
- **D6.64 Sprint 4** — vessel/PSC/changelog/audit AI co-pilots in `me.py` + marketing surfaces.
- **D6.63** — personalized reasoning across chat + Co-Pilot cards + Career Path.
- **D6.62** — mariner sea-time logger + PDF credential package.
- **D6.60** — hedge judge: Haiku gates fallback firing.
- **D6.59** — cascading ensemble + admin "view as user" preview.
- **D6.58** — two-tier web fallback surface; off-topic scope gate w/ daily cap + abuse alert; hedge audit feedback loop; Big-3 ensemble fallback (Claude + GPT + Grok).
- **D6.51** — pre-retrieval query distillation for verbose first turns.
- **D6.49** — Crew tier / Wheelhouse: workspaces CRUD + role gates, workspace-scoped chat (backend + frontend), invite flow, billing wired end-to-end.
- **D6.48** — web search fallback (Phase 1 + Phase 2 backend, UI, single-shot review endpoint).
- **D6.46/D6.47** — multilingual flag-state expansion (FR/DE/ES/IT/GR), corpus badges.
- **D6.45** — IACS UR full series + MPA SG brute-force discovery.
- **D6.42/D6.43** — STCW + MARPOL amendments; refresh cadence.
- **D6.41** — Polar Code + IGF Code + BWM Convention.
- **D6.36** — IMDG manual UN entries + HK MD auto-discovery.
- **D6.32 → D6.34** — admin overview + verbosity controls (settings + per-message chips).
- **D6.31** — user persona + jurisdiction_focus profile.
- **D6.29/D6.30** — layered jurisdictional context (chat title + user fingerprint).
- **D6.23 → D6.23g** — multi-flag corpus severance, UI catch-up for international corpus, recover answers after phone-lock / SSE drop, force-dynamic on root, kill stale PWA service worker.
- **D6.20 → D6.22** — AMSA + LISCR + IRI + Singapore + HK + Bahamas + TC corpora.
- **D6.18** — UK MCA notices ingest (first non-US corpus).
- **D6.17** — flag-state-driven jurisdictional scoping + tonnage plausibility check.
- **D6.16** — UN-number retrieval grounding + UN-claim post-generation verifier.
- **D6.12** — IMDG Code 2024 Edition.
- **D6.11** — MARPOL Convention + supplements.
- **D6.8** — mariner → CFR vocab synonym expansion (closes the documented vocab-mismatch failure mode).
- **D6.7** — free traffic analytics from Caddy logs.
- **D6.4** — USCG MSM ingest + conversational-followup retrieval.
- **D6.1/D6.2/D6.3** — two-tier pricing foundation (Mate + Captain), Mate monthly cap, pricing redesign + `/womenoffshore` + referral capture.

Corpus today: ~77,111 chunks across 50 sources (vs. ~42K / 15 sources at the previous roadmap). Eval at 96.1% A-or-A− on the latest 152-question regression run.

---

## Now / this week

The audit's small-but-real items still open after the 2026-05-09 sprint.

1. **Bump `next` 15.5.14 → 15.5.15+.** 10 min. DoS CVE GHSA-q4gf-8mx6-v5v3. `pnpm up next` in apps/web, then `scripts/deploy.sh`. (Was item #4 — only one of the original "Now / this week" set still open.)
2. **Click through the UptimeRobot setup.** 15 min. Runbook at `docs/runbook-uptimerobot.md`. 7 monitors with body-keyword assertions covering `/api/health` + 5 frontend routes + a backup-heartbeat. Free tier, optional Discord webhook for phone push. The runbook is shipped; only the click-through and Discord wiring are pending.

---

## Next 1-2 weeks

Real iterations, prioritized.

3. **Layer C — UX inversion when retrieval miss is hard.** ~3 hr code + 1 hr eval. Today's flow on a hard retrieval miss: confused main answer + a correct web-fallback panel below or beside it. Two surfaces, two messages, the user has to notice the secondary panel. New behavior: when `hedge_judge` classifies the response as `complete_miss` AND a `web_fallback_responses` row exists with `confidence ≥ 3`, lead with the web-fallback content as the primary answer (with explicit "I couldn't find this in the formal corpus; here's what trusted maritime sources say" framing). Big expected win for the 35.7%/7d bad-answer rate — the John Collins fire-wire query specifically would have flipped from a confused electric-cable explanation to the correct ETOP answer that web fallback already produced. Eval delta needs measurement before flipping on for everyone; could ship behind a feature flag with a 10% rollout first.
4. **Phase 2 — multi-model maritime glossary brainstorm.** ~6-8 hr. New `scripts/build_maritime_glossary.py` calling Sonnet 4.6, GPT-5, Grok-4, Gemini-2.5-Pro in parallel via API with structured prompts (roles primed as senior maritime auditor, asked for entries across 9 categories: tanker, deck, engineering, mooring/towing, cargo, navigation, safety, fishing-specific, port-state). Each model returns ~80-150 entries; total ~400-500 before dedup. Then programmatic verification: corpus presence of formal terms, citation-existence checks against the regulations table, cross-model agreement, optional Brave/Bing corroboration. Output bucketed `verified` / `likely` / `review` / `reject` for Karynn's curation gate (1-2 hr of her time). Final glossary lands at `packages/rag/rag/maritime_glossary.py` upgrading current confidence=1 entries to confidence=2/3. The 52 entries seeded in the post-audit sprint are the foundation; this systematizes ongoing curation. Cost: ~$2-5 in API calls, one-time. Reusable: re-run quarterly to refresh.
5. **OSHA no-cite clause** in chat system prompt. ~30 min. ~21% of chats currently regen because synthesis invents 29 CFR Part 1910 citations that the verifier strips. Add the redirect to 46 CFR Subchapter V to `prompts.py`.
6. **`46 CFR 95.25` family ingest gap.** ~1-2 hr. The 2026-05-09 eval's V1/S-033 failure cited `46 CFR 95.25-1` which doesn't exist in the corpus (zero rows). The whole 95.25 subpart (fire-protection equipment specs under Subchapter F) is missing from `cfr_46`. Quick re-ingest of the 95.25-* sections via the existing CFR pipeline. Discovered during the post-audit sprint diagnosis; gateway to a broader corpus-completeness audit.
7. **CI workflow.** ~2 hr. `.github/workflows/ci.yml` running `pnpm lint`, `tsc --noEmit`, `pytest` on PRs. Locks deploy hygiene now that `scripts/deploy.sh` exists.
8. **First three tests.** ~3 hr total. Stripe webhook handler against a recorded fixture; `study._shuffle_question_options` / `_citation_base` / `_parse_json_response`; `rag.retriever._extract_identifiers` / `_extract_keywords`. All three are pure functions today — no DB fixtures required.
9. **Extract `app/llm_helpers.py`.** ~3 hr. The Sonnet-call boilerplate is copy-pasted 6 times in `me.py`; `_parse_json` exists in 6 places (me.py, study.py, documents.py, citation_oracle.py, query_rewrite.py, reranker.py). Largest source of accidental drift in the codebase.
10. **Caddy security headers + rate-limit `/api/domain-check`.** ~30 min. Add `header { ... }` block (HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP). 50 cert directories in Caddy with scanner-injected hostnames suggests `/api/domain-check` is returning 200 on garbage subdomains.
11. **Sentry frontend `environment` tag.** 5 min. `apps/web/src/instrumentation-client.ts` and `instrumentation.ts` omit it; every event currently shows up untagged.
12. **UN-number citation grounding fix** (eval V1/S-046 isocyanate spill). ~1 hr. Different verification path than the CFR/MSC fix shipped 2026-05-09 — UN numbers go through `_collect_unverified_un_numbers` in engine.py which checks if the UN ID was *retrieved* (grounded) before being cited. The IMDG / ERG ingest may not be tagging UN numbers in a queryable way. Investigate the grounding logic before deciding.

---

## Within 30 days

Architectural items that take a session or two each.

13. **Move SpiritFlow off the box.** ~6 hr + $24/mo. Provision a dedicated droplet for SpiritFlow (or the reverse — give RegKnots its own box). Layer 1 cgroup caps (shipped 2026-05-09) close most of the practical exposure but the shared tenancy is still the largest architectural coupling risk before traffic ramps.
14. **Test-coverage sprint.** ~2 days. Auth flow, billing webhook, message-cap gate, the six Sonnet endpoints in `me.py`, Study Tools router. The gap isn't a bug today, but at the current ship cadence (35+ fix commits in 14 days, zero reverts) the lack of any safety net is the largest source of latent regression risk.
15. **Corpus-completeness audit.** ~4 hr. The 2026-05-09 eval found `46 CFR 95.25-*` entirely missing from the corpus (item #6 patches it). Generalize: which CFR subparts have zero rows where they should have many? Which IMO Code chapters are partial? Which flag-state corpora claim a section that doesn't actually exist? Output: a CSV of identified gaps + a per-source priority order for re-ingest. Pre-stage for the corpus-refresh sprint below.
16. **Documentation completion.** ~6 hr. `docs/architecture.md` (services + data flow), `docs/runbook.md` (deploy / restart / restore / rotate / rollback), `docs/glossary.md` (CFR, COLREGs, MMC, STCW, MSIB, etc.), per-package READMEs (`apps/api`, `apps/web`, `packages/rag`, `packages/ingest`), `SECURITY.md`, `CONTRIBUTING.md`. The repo-root README and CLAUDE.md were created in the audit pass; everything else is the gap.
17. **Off-host backup destination.** ~1 hr. B2 or S3 nightly upload of the daily local pg_dump (already shipped in the post-audit sprint, see Done section). Local backups survive every failure mode except disk loss; this closes that hole.

---

## Deferred / re-check next quarter

- **Embedding upgrade to `text-embedding-3-large`.** April audit and this audit agree it's not the bottleneck. $3.54 + 4× pgvector storage cost; don't move until a concrete failure mode demands it.
- **Hot-replica Postgres.** Overkill at current scale (DB is 1528 MB, 1 active + 8 idle connections, 1.9M committed xacts, 0 deadlocks). Revisit at Tier 4 in scaling-roadmap.md (~500 active users/day).
- **Corpus refresh sprint — STCW (2017-07), MARPOL (2022-11), USCG MSM (2021-09).** Three stale outliers. MARPOL is the highest user-visible risk because Annex VI EEXI/CII rules and fuel-sulphur enforcement details have moved. Schedule a focused sprint when traffic stabilizes.
- **Drop `'use client'` from marketing landings → RSC + client islands.** All 42 pages are client components today. Cumulative bundle hit is real but not blocking.

---

## Done — items closed since 2026-04-20

Lifting from the previous roadmap so the open list stays calibrated.

### Closed in the post-D6.83 audit remediation sprint (2026-05-08 → 2026-05-09)

- **JWT signing key rotation.** `.env` env var renamed `REGKNOTS_SECRET_KEY` → `REGKNOTS_JWT_SECRET_KEY`. API now signs JWTs with a real 64-char secret instead of the hardcoded default `dev-secret-key-...`. All active sessions invalidated once on restart (expected and one-time).
- **`.env` permissions tightened to mode 0600.** Co-tenant `spiritflow` user can no longer read RegKnots secrets.
- **Daily Postgres backup operational.** `regknots-backup.timer` fires daily at 03:00 UTC, runs `scripts/backup_postgres.sh` (pg_dump from container | pigz -3 | gzip-integrity-check + zgrep schema-shape check), 14-day retention, mode 0600 on output. First backup confirmed 549 MB on disk. Took 4 iterations of script tuning to handle pipefail/SIGPIPE quirks (gzip -9 timeout → pigz -3, gunzip-pipe-grep false negative → subshell + head + grep). Closes the RPO=∞ exposure.
- **Failed `regknots-refresh-weekly.service` revived.** Root cause was that all `scripts/*.sh` were committed as mode 100644 (no exec bit) because the worktree is on Windows. `git reset --hard` on the VPS landed `corpus_refresh.sh` as 0644, systemd's exit 203 (EXEC) means "couldn't exec the binary." Same trap was waiting on `deploy.sh`, `smoke.sh`, `backup_postgres.sh`. Fix: `git update-index --chmod=+x` on all four. After re-pull on VPS, refresh-weekly started running clean. ~30-second fix, made possible by accidentally noticing the mode mismatch during diagnosis.
- **Layer 1 OOM defense.** Systemd cgroup caps via drop-ins at `deploy/systemd/regknots-{api,web,worker}.service.d/memory.conf`: api 1.5G/2G, web + worker 512M/1G. When a service grows past `MemoryMax` the cgroup OOM-kills it; `Restart=always` brings it back; the rest of the box stays green. **Structurally closes the May 1 incident class** — global OOM that took the box for 9 hours can no longer happen without a kernel bug.
- **2 GB swap on `/swapfile`** with `vm.swappiness=10` and `/etc/fstab` entry. Kernel can bleed cold pages instead of OOM-killing under transient pressure. Persisted across reboots.
- **`scripts/run_ingest.sh` wrapper.** Wraps ad-hoc ingest in `systemd-run --slice=regknots-ingest.slice --property=MemoryMax=1.5G --property=CPUQuota=150% ...` so a runaway ingest dies in its own cgroup, not the whole box. CLAUDE.md flagged the wrapper as the required path; bare `uv run python -m ingest.cli` is now an anti-pattern.
- **Maritime glossary v1 (`packages/rag/rag/maritime_glossary.py`).** 52 confidence-tagged slang→formal entries seeded from Sonnet's domain knowledge: towing (`fire wire` → emergency towing-off pennant), mooring, cargo (`ullage`, `dunnage`, `tally`), deck (`scupper`, `lazarette`, `monkey island`), engineering (`donkeyman`, `oiler`), safety (`mob`, `epirb`, `sart`), navigation (`dr`, `ais`, `ecdis`), certificates (`mmc`, `coi`, `iopp`), PSC, drills. All confidence=1; multi-model verification pass tracked under "Phase 2" above.
- **Maritime-slang few-shot in query_rewrite prompt.** `_REWRITE_SYSTEM_PROMPT` now opens with explicit slang-recognition guidance + 9 worked examples (fire wire → ETOP, etc.) + 25-entry quick-reference table. Attacks the root cause of the John Collins fire-wire miss: not Haiku capability but prompt shape boxing it into bottom-up corpus-vocab translation.
- **HYBRID_RETRIEVAL_ENABLED flag flipped on.** D6.71's dark-launched BM25+RRF retrieval is now the default for general queries (sources=None). Eval re-run showed expected behavior — more diverse retrieval surfaces (specifically more IMO IGC / IMO HSC content for gas-carrier and CO2 questions) which exposed the citation-verifier format-mismatch bug separately addressed below.
- **Citation verifier handles CFR parent-range and IMO-family MSC.X(Y) sources** (commit 5d2c567). When the model writes `46 CFR 142` (no subsection), verifier now LIKE-matches against `46 CFR 142.%` instead of failing exact match. When the model writes `MSC.370(93)`, verifier checks `imo_igc`, `imo_hsc`, `imo_ibc`, `fss`, `lsa`, `marpol_supplement`, `ism_supplement` in addition to the original `solas_supplement` / `stcw_supplement`. Targeted DB queries confirmed 6 of 7 specific eval failure cases now resolve. Expected eval delta: 6-8 of 12 F's flip to A on re-run.
- **UptimeRobot setup runbook** at `docs/runbook-uptimerobot.md`. 7 monitors with body-keyword assertions covering `/api/health` + 5 frontend routes + a backup heartbeat. Free tier ($0/mo), optional Discord webhook for phone push notifications. The runbook is shipped; the click-through is item #2 above.
- **Memory files refreshed.** `MEMORY.md` index, `project_db_constraint.md`, `project_retrieval_vocab_mismatch.md`, `project_deployment_procedure.md` all updated to reflect resolved status.
- **Repo-root README.md and CLAUDE.md created** (both were missing). PROJECT_STATE.md and roadmap.md (this file) refreshed against verified live numbers.

### Closed earlier in this cycle

- **§1f — `scripts/deploy.sh`.** Shipped 2026-05-07 (107ee6a). Smoke script ships alongside.
- **Vocab-mismatch failure mode** (was a memory-flagged "no fix yet"). Closed by D6.8 — `synonyms.py` ships 6 user-vocab entries (lifejacket, log, mob, stability, stencil/stenciled/stenciling) with curated CFR-vocab expansions; `query_rewrite.py` produces 2-3 reformulations every chat (default ON); two intent expanders (drill-frequency, equipment-marking) gate on dual signals.
- **`ism_supplement` migration drift** (was a "added live, not in migration files" memory flag). Closed by migration `0090_add_nmc_exam_bank_source.py` (2026-05-07) which explicitly defines the canonical source list including `ism_supplement`.
- **§1a — GovDelivery forward channel / freshness.** Replaced by D6.75 weekly NMC corpus refresh via systemd timer + the existing USCG bulletin pipeline. The "real-time differentiator" V2 path remains deferred — current weekly cadence is fine for current pilot users.
- **§1b — retrieval-side freshness filtering.** Subsumed by D6.42/D6.43 (STCW + MARPOL amendments + refresh cadence) and the citation oracle (D6.70). Re-open as a discrete item if a stale-citation user complaint surfaces.
- **§2a — content_hash normalization.** Replaced by the threshold-gated content-hash sensitivity that already shipped in Sprint B3; refresh cadence now driven by weekly systemd timer rather than eCFR republish event.
- **§5.1 / §5.2 — Cowork weekly ops cadence and folder hygiene.** Out of scope for this strategic doc; if revived, route through the audit's "Workflow / automation opportunities" table (retrieval-miss review, corpus-freshness sentinel, hedge-rate report).
- **2FA / TOTP** (was §2d). Not in the audit's 30-day list. Remains deferred; revisit when paid-tier user count crosses a threshold that justifies the lift.

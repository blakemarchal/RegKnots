# RegKnots Roadmap

**Last updated:** 2026-05-08 (post-D6.83)

This is the strategic shipped/in-flight/upcoming view of the product. It's separate from `docs/PROJECT_STATE.md` (operational one-pager — alembic head, current corpus, hot-button bugs) and `docs/scaling-roadmap.md` (capacity thresholds and what each one triggers). Findings, calibration, and the prioritized 30-day list lift directly from `docs/sprint-audits/full-system-audit-2026-05-08.md`. The previous version is archived at `docs/archive/roadmap-2026-04.md`.

---

## Recent shipped (last 14 days)

Working backwards through `git log --since="2026-04-22"`. Sprint numbers are the ones in commits, not invented.

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

The audit's "before you walk away" list. All small.

1. **Rotate JWT signing key.** 5 min. `/opt/RegKnots/.env` has `REGKNOTS_SECRET_KEY` but the code reads `REGKNOTS_JWT_SECRET_KEY` (config.py:17), so JWTs are signed with the hardcoded default. Rename the var and restart `regknots-api`. Critical — full account-takeover risk if untouched.
2. **Tighten `.env` perms.** 30 sec. `chmod 600 /opt/RegKnots/.env`. Co-tenant `spiritflow` user can `cat` it today.
3. **Daily Postgres backups.** 10 min. `/etc/cron.daily/regknots-pgdump`, 14-day local retention, `/var/backups/regknots/`. RPO=∞ today.
4. **Bump `next` 15.5.14 → 15.5.15+.** 10 min. DoS CVE GHSA-q4gf-8mx6-v5v3. `pnpm up next` in apps/web, then `scripts/deploy.sh`.
5. **Fix the failed `regknots-refresh-weekly.service`.** ~15 min. In `failed (code=203/EXEC)` since 2026-05-03 — weekly CFR + USCG bulletin refresh hasn't run for 5 days. Likely a path issue post-deploy.
6. **Update memory files.** Done in this audit pass. Vocab-mismatch is fixed (D6.8 → synonyms.py + query_rewrite.py); `ism_supplement` is in migration 0090.

---

## Next 1-2 weeks

Real iterations, prioritized.

7. **Flip on hybrid BM25 + dense retrieval.** ~30 min. Set `HYBRID_RETRIEVAL_ENABLED=true`, restart API, re-run eval, compare to 96.1% baseline. Already built (D6.71); just needs the flag flipped after eval comparison. Highest leverage RAG change available.
8. **OSHA no-cite clause** in chat system prompt. ~30 min. ~21% of chats currently regen because synthesis invents 29 CFR Part 1910 citations that the verifier strips. Add the redirect to 46 CFR Subchapter V to `prompts.py`.
9. **External alerting on `/api/health`.** ~1 hr. Better Uptime / healthchecks.io free tier, SMS path. Closes the May 1 OOM-crashloop scenario where the API was down 9+ hours and the only signal would have been a customer.
10. **2 GB swap + per-service `MemoryHigh`/`MemoryMax`.** ~15 min. Prevents the May 1 incident class on the 4 GB shared box.
11. **CI workflow.** ~2 hr. `.github/workflows/ci.yml` running `pnpm lint`, `tsc --noEmit`, `pytest` on PRs. Locks deploy hygiene now that `scripts/deploy.sh` exists.
12. **First three tests.** ~3 hr total. Stripe webhook handler against a recorded fixture; `study._shuffle_question_options` / `_citation_base` / `_parse_json_response`; `rag.retriever._extract_identifiers` / `_extract_keywords`. All three are pure functions today — no DB fixtures required.
13. **Extract `app/llm_helpers.py`.** ~3 hr. The Sonnet-call boilerplate is copy-pasted 6 times in `me.py`; `_parse_json` exists in 6 places (me.py, study.py, documents.py, citation_oracle.py, query_rewrite.py, reranker.py). Largest source of accidental drift in the codebase.
14. **Caddy security headers + rate-limit `/api/domain-check`.** ~30 min. Add `header { ... }` block (HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP). 50 cert directories in Caddy with scanner-injected hostnames suggests `/api/domain-check` is returning 200 on garbage subdomains.
15. **Sentry frontend `environment` tag.** 5 min. `apps/web/src/instrumentation-client.ts` and `instrumentation.ts` omit it; every event currently shows up untagged.

---

## Within 30 days

Architectural items that take a session or two each.

16. **Move SpiritFlow off the box.** ~6 hr + $24/mo. Provision a dedicated droplet for SpiritFlow (or the reverse — give RegKnots its own box). The shared 4 GB tenancy is the largest coupling risk before traffic ramps; several of the May 1-2 OOMs targeted the cohabitant tenant's user sessions.
17. **Test-coverage sprint.** ~2 days. Auth flow, billing webhook, message-cap gate, the six Sonnet endpoints in `me.py`, Study Tools router. The gap isn't a bug today, but at the current ship cadence (28+ fix commits in 14 days, zero reverts) the lack of any safety net is the largest source of latent regression risk.
18. **Documentation completion.** ~6 hr. `docs/architecture.md` (services + data flow), `docs/runbook.md` (deploy / restart / restore / rotate / rollback), `docs/glossary.md` (CFR, COLREGs, MMC, STCW, MSIB, etc.), per-package READMEs (`apps/api`, `apps/web`, `packages/rag`, `packages/ingest`), `SECURITY.md`, `CONTRIBUTING.md`. The repo-root README and CLAUDE.md were created in the audit pass; everything else is the gap.
19. **Off-host backup destination.** ~1 hr. B2 or S3 nightly upload of the local pg_dump. Local backups (item #3) survive every failure mode except disk loss; this closes that hole.

---

## Deferred / re-check next quarter

- **Embedding upgrade to `text-embedding-3-large`.** April audit and this audit agree it's not the bottleneck. $3.54 + 4× pgvector storage cost; don't move until a concrete failure mode demands it.
- **Hot-replica Postgres.** Overkill at current scale (DB is 1528 MB, 1 active + 8 idle connections, 1.9M committed xacts, 0 deadlocks). Revisit at Tier 4 in scaling-roadmap.md (~500 active users/day).
- **Corpus refresh sprint — STCW (2017-07), MARPOL (2022-11), USCG MSM (2021-09).** Three stale outliers. MARPOL is the highest user-visible risk because Annex VI EEXI/CII rules and fuel-sulphur enforcement details have moved. Schedule a focused sprint when traffic stabilizes.
- **Drop `'use client'` from marketing landings → RSC + client islands.** All 42 pages are client components today. Cumulative bundle hit is real but not blocking.

---

## Done — items closed since 2026-04-20

Lifting from the previous roadmap so the open list stays calibrated.

- **§1f — `scripts/deploy.sh`.** Shipped 2026-05-07 (107ee6a). Smoke script ships alongside.
- **Vocab-mismatch failure mode** (was a memory-flagged "no fix yet"). Closed by D6.8 — `synonyms.py` ships 6 user-vocab entries (lifejacket, log, mob, stability, stencil/stenciled/stenciling) with curated CFR-vocab expansions; `query_rewrite.py` produces 2-3 reformulations every chat (default ON); two intent expanders (drill-frequency, equipment-marking) gate on dual signals.
- **`ism_supplement` migration drift** (was a "added live, not in migration files" memory flag). Closed by migration `0090_add_nmc_exam_bank_source.py` (2026-05-07) which explicitly defines the canonical source list including `ism_supplement`.
- **§1a — GovDelivery forward channel / freshness.** Replaced by D6.75 weekly NMC corpus refresh via systemd timer + the existing USCG bulletin pipeline. The "real-time differentiator" V2 path remains deferred — current weekly cadence is fine for current pilot users.
- **§1b — retrieval-side freshness filtering.** Subsumed by D6.42/D6.43 (STCW + MARPOL amendments + refresh cadence) and the citation oracle (D6.70). Re-open as a discrete item if a stale-citation user complaint surfaces.
- **§2a — content_hash normalization.** Replaced by the threshold-gated content-hash sensitivity that already shipped in Sprint B3; refresh cadence now driven by weekly systemd timer rather than eCFR republish event.
- **§5.1 / §5.2 — Cowork weekly ops cadence and folder hygiene.** Out of scope for this strategic doc; if revived, route through the audit's "Workflow / automation opportunities" table (retrieval-miss review, corpus-freshness sentinel, hedge-rate report).
- **2FA / TOTP** (was §2d). Not in the audit's 30-day list. Remains deferred; revisit when paid-tier user count crosses a threshold that justifies the lift.

# RegKnots Full-System Audit — 2026-05-08

Five-dimension audit on the eve of the marketing push. Five parallel research passes covering security, code quality + tests, RAG/corpus health, infrastructure + ops, and documentation. Written calibrated — most findings are "this is fine" and called out as such; a small number are real and ranked.

**Bottom line:** the product is in better shape than most early-stage SaaS. Auth, retrieval, deployment hygiene (after today), feature velocity, citation accuracy — all good or better. **Two findings are real-and-fixable-in-30-min** and worth doing before you step away. The rest can wait for next week.

---

## TL;DR — "before you walk away" checklist

If you do nothing else from this audit, do these. Each is <15 min on the VPS.

### 1. Rotate JWT signing key (CRITICAL — 5 min, full account takeover risk if untouched)

The `.env` on prod has `REGKNOTS_SECRET_KEY=...` but the code reads `REGKNOTS_JWT_SECRET_KEY` (config.py:17). The variable mismatch means the API is signing every JWT with the **hardcoded default value** `"dev-secret-key-change-in-production-use-REGKNOTS_JWT_SECRET_KEY"` — itself a hint to the right env var name. Anyone reading the source can forge a token for your hardcoded admin (`kdmarchal@gmail.com`). Confirmed live.

```bash
ssh root@68.183.130.3 'cat /opt/RegKnots/.env | grep -i secret'
# If you see REGKNOTS_SECRET_KEY=<value> but NOT REGKNOTS_JWT_SECRET_KEY=<value>, fix:
ssh root@68.183.130.3 'sed -i "s/^REGKNOTS_SECRET_KEY=/REGKNOTS_JWT_SECRET_KEY=/" /opt/RegKnots/.env'
ssh root@68.183.130.3 'systemctl restart regknots-api'
```

This will invalidate every existing JWT — every user gets logged out once. That's the cost. Do it before marketing traffic arrives, not after.

### 2. Tighten `.env` permissions (HIGH — 30 sec)

`/opt/RegKnots/.env` is currently `-rw-r--r--` (mode 0644). The `spiritflow` user account on the same box can `cat` it and pull every Anthropic / Stripe live / OpenAI / Resend / Sentry secret you have.

```bash
ssh root@68.183.130.3 'chmod 600 /opt/RegKnots/.env && ls -la /opt/RegKnots/.env'
```

### 3. Set up daily Postgres backups (HIGH — 10 min, full data-loss risk if untouched)

There are **zero database backups today.** If `/dev/vda1` corrupts right now, every user message, survey response, retrieval-miss log, customer record, and Stripe-link is gone. The corpus you can re-ingest from raw PDFs (4–12 hr); the user data is permanent loss.

```bash
ssh root@68.183.130.3 bash <<'EOF'
mkdir -p /var/backups/regknots
cat > /etc/cron.daily/regknots-pgdump <<'CRON'
#!/usr/bin/env bash
# Daily pg_dump → /var/backups/regknots/, keep 14 days.
set -euo pipefail
ts=$(date -u +%Y%m%d-%H%M%S)
out="/var/backups/regknots/regknots-${ts}.sql.gz"
docker exec regknots-postgres pg_dump -U regknots regknots | gzip > "$out"
find /var/backups/regknots -name 'regknots-*.sql.gz' -mtime +14 -delete
CRON
chmod +x /etc/cron.daily/regknots-pgdump
# One immediate run to verify + seed the directory
/etc/cron.daily/regknots-pgdump && ls -la /var/backups/regknots/
EOF
```

This gives you a 24h RPO. Off-host upload (B2/S3) is a separate next step but the local backup alone is 95% of the safety; it survives every failure mode except a full disk loss, and from a full disk loss you'd still be re-provisioning the box anyway.

If you can do all three before your weekend break, the system is meaningfully safer. The rest of this doc you can read at leisure.

---

## Section 1 — Security

**Auditor's calibration:** The auth model is solid (Argon2 hashing, 15-min access tokens with rotating refresh tokens stored as sha256 with replay revocation, all `/me/*` endpoints gated, Stripe webhook signature verified, CORS regex tight). The chat endpoint has its own per-user rate limit. SQL is parameterized everywhere I traced. File uploads have size + MIME limits. **Outside the JWT-secret misconfiguration above, this is a well-built surface.**

| Sev | Finding | Fix |
|---|---|---|
| **Critical** | JWT signed with hardcoded default — `.env` on VPS has `REGKNOTS_SECRET_KEY` but code reads `REGKNOTS_JWT_SECRET_KEY`. Forge-any-user. | TL;DR #1 |
| **High** | `/opt/RegKnots/.env` is mode 0644, world-readable. Co-tenant `spiritflow` user can read every secret. | TL;DR #2 |
| **High** | `next@15.5.14` has DoS CVE GHSA-q4gf-8mx6-v5v3 (fix in 15.5.15). | `cd apps/web && pnpm up next` |
| **Medium** | No HTTP security headers — no HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, CSP. | Add `header { ... }` block to `/etc/caddy/Caddyfile` regknots block |
| **Medium** | `python-multipart 0.0.24` has 2 DoS CVEs (CVE-2026-40347, CVE-2026-42561). Behind auth, blast radius narrow. | Bump to 0.0.27+ in `apps/api/pyproject.toml` |
| **Medium** | `fail2ban` not installed. SSH password auth is already off (good), so narrow surface. | `apt install fail2ban` |
| **Low** | Sentry has no `before_send` PII filter; `traces_sample_rate=0.1` captures 10% of chat spans with the query field. | Add a scrub function on both backend + frontend Sentry init |
| **Low** | `chat.query` Pydantic field has no `max_length`. Auth-gated, so bounded. | `query: str = Field(min_length=1, max_length=4000)` |
| **Low** | Password policy: min-8, no complexity, no breach-list check. | Optional: bump min to 10 + zxcvbn or HIBP check |
| **Low** | uvicorn / Next.js bind 0.0.0.0:8000 / :3000 (UFW blocks externally). | Defense-in-depth: bind 127.0.0.1 only |
| **Low** | 3 high + 4 moderate `pnpm audit` findings, all transitive through `@ducanh2912/next-pwa → workbox-build`. Build-time only, doesn't ship to user. | Watch for next-pwa to update; optionally `pnpm.overrides` to force lodash + serialize-javascript bumps |
| **OK** | No secrets in git history. Searched for `sk_live`, `sk-ant`, `whsec_` — only `.env.example` placeholders. | Nothing to do |
| **OK** | JWT auth surface (HS256, 15-min access, 7-day rotating refresh, sha256-hashed-at-rest, family revocation on replay with 10s grace). Argon2 hashing. | Nothing to do (after #1) |
| **OK** | Stripe webhook signature is verified, no bypass path. | Nothing to do |
| **OK** | CORS regex `^https://([a-z0-9-]+\.)?regknots\.com$` is tight. | Nothing to do |
| **OK** | No SQL injection found. All `f"..."` SET clauses use whitelisted field names; values always go through `$N` parameters. | Nothing to do |
| **OK** | File upload validation (10 MB cap, MIME whitelist, UUID filenames, no path traversal). | Nothing to do |
| **OK** | Chat rate limit per-user (10/min via Redis); study tools share the 200/mo cap; web fallback has its own 10/day. | Nothing to do |
| **OK** | Postgres + Redis bound to 127.0.0.1. | Nothing to do |

---

## Section 2 — Code quality + tests

**Auditor's calibration:** Type safety is strong (`tsc --noEmit` clean; Pydantic response models everywhere). Logging is structured and consistent. No dead code worth chasing. **The big finding is the test gap.** It's not a bug today, but at the current ship cadence (28+ fix commits in 14 days, zero reverts) the lack of any safety net is the largest source of latent regression risk.

### Real findings

| Sev | Area | Finding |
|---|---|---|
| **Critical** | **Test coverage** | Zero tests anywhere. `apps/api/tests/` doesn't exist. `apps/web` has no test runner installed. The four `test_*.py` files in `packages/` are stand-alone diagnostic CLIs that hit live services, not pytest-collected. Nothing tests the auth flow, the Stripe webhook, the message-cap gate, the six Sonnet endpoints in me.py, or any Study Tools code. |
| **High** | **LLM-helper duplication** | The Sonnet-call boilerplate is copy-pasted **6 times in `me.py`** (renewal-readiness, career-progression, vessel-analysis, psc-prep, compliance-changelog, audit-readiness). The `_parse_json` helper exists in **6 places** (me.py, study.py, documents.py, citation_oracle.py, query_rewrite.py, reranker.py). Single largest source of accidental drift in the codebase. |
| **Medium** | **Stripe webhook leak** | `billing.py:68-71` re-raises `str(exc)` to Stripe with no logging. A DB error text could leak; the webhook is also retried on every 400, so noise compounds. `logger.exception(...)` and a generic detail string. |
| **Medium** | **Swallowed email-send failures** | `auth.py:184-199` swallows three sequential email-send failures (auto-claim invites, welcome email, verification email) on register with **zero log signal**. A user can register and never receive the verification email and you'd never know. |
| **Medium** | **Live Stripe fetch in `/billing/status`** | `billing.py:182-191` issues a fresh `stripe.Subscription.retrieve` on every dashboard load. 100–300 ms latency on a hot endpoint; cache-able. |
| **Medium** | **Cap-counting + study-pool ILIKE perf** | `study.py:250` `COUNT(*) FROM study_generations WHERE user_id = $1 AND created_at >= date_trunc('month', NOW())` fires on every quiz/guide POST — needs index on `(user_id, created_at)`. `study.py:307-310` uses `ILIKE '%' \|\| $1 \|\| '%'` on `full_text` — leading wildcard, sequential scan. Trigram index migration 0033 may already cover this; verify. |
| **Medium** | **Sentry missing `environment` tag (frontend)** | `apps/web/src/instrumentation-client.ts` and `instrumentation.ts` omit `environment: ...`. Every event shows up untagged. |
| **Low** | **`'use client'` on every page** | All 42 pages are client components. Marketing landings (`/landing`, `/giving`, `/coverage`, `/whitelisting`) ship full React runtime when they could be streaming RSC. Not urgent; cumulative bundle hit is real. |
| **Low** | **`Optional[]` vs `\|`-union style drift** | 53 `Optional[...]` occurrences across routers; only `me.py` and `study.py` use `from __future__ import annotations`. Stylistic. |
| **OK** | TypeScript | `tsc --noEmit` clean |
| **OK** | Logging discipline | All app code goes through `logging.getLogger`. No stray `print()`. |
| **OK** | SQL parameterization | Verified safe across all routers |
| **OK** | Recent regressions | 28+ fix commits in 14 days, zero reverts. Pace is high but nothing has been catastrophic. |

### Recommended order if/when you tackle this

1. Extract `app/llm_helpers.py` (or `rag/json_utils.py`) with `extract_text_blocks`, `parse_json_loose`, `parse_json_or_salvage` — replaces 6 duplicates. Then `_sonnet_json(system, payload, max_tokens)` collapses the 6 me.py endpoints from ~80 lines each to ~25.
2. Three highest-leverage tests to write first (each pure-Python given fixtures, no live DB):
   - `app.stripe_service.handle_webhook_event` against a recorded webhook fixture.
   - `app.routers.study._shuffle_question_options`, `_citation_base`, `_parse_json_response` — already pure functions.
   - `rag.retriever._extract_identifiers` / `_extract_keywords` — already exercised by `test_hybrid_search.py`, just rename `def main` to `def test_*` and add `assert`s.
3. `auth.py:184-199` email-send block — wrap each with `logger.warning("welcome email failed: %s", exc)`.
4. Stripe webhook handler — `logger.exception` + generic detail.

---

## Section 3 — RAG corpus + retrieval

**Auditor's calibration:** Mature, well-instrumented, outperforming most production RAG I've audited. **96.1% A-or-A−** on the latest 152-question regression eval. All modern stack components shipped: multi-query rewrite (Haiku), Haiku reranker, citation oracle, source-diversified fetch, jurisdiction filter, vessel-profile boosts, synonym + intent expansion. Hybrid BM25+RRF is **built and dark-launched** behind a feature flag.

### Corpus — healthy

- **77,111 chunks across 50 sources.** 100% embedding coverage. Vector dim 1536. Total ~108.9M chars / 27.2M tokens. Top sources: cfr_49 (15,838), cfr_46 (10,523), cfr_33 (7,192), nma_rsv (5,426), nvic (3,453), uscg_msm (3,048), iacs_ur (2,981), nmc_exam_bank (2,938), uscg_bulletin (2,232), imdg (2,129).
- Chunk-size distribution is appropriate. Median chunk falls in the 1.2K–3K char band.
- **3 stale outliers**: STCW (2017-07), MARPOL (2022-11), USCG MSM (2021-09). MARPOL is the highest user-visible risk — Annex VI EEXI/CII rules and fuel-sulphur enforcement details have moved.

### Two memory-flagged "known issues" are actually resolved

- **Vocab mismatch** (memory: "no fix yet") — **memory is stale.** `synonyms.py` has 6 user-vocab entries (lifejacket, log, mob, stability, stencil/stenciled/stenciling) with curated CFR-vocab expansions; `query_rewrite.py` produces 2-3 reformulations every chat (default ON); two intent expanders (drill-frequency, equipment-marking) fire on dual-signal gates.
- **`ism_supplement` migration drift** (memory: "added live, not in migration files") — **memory is stale.** Migration `0090_add_nmc_exam_bank_source.py` (2026-05-07) explicitly defines the canonical source list including `ism_supplement`. `ism_supplement` has 23 chunks (cyber risk + designated person + near-miss reporting + Resolution A.1118(30)) and is being retrieved.

I'll update both memory files at the end of this audit pass.

### Real findings

| Sev | Finding | Fix |
|---|---|---|
| **High** | `regknots-refresh-weekly.service` has been in `failed (code=203/EXEC)` since 2026-05-03. Weekly CFR + USCG bulletin refresh hasn't run for 5 days. Likely path issue post-deploy. | Diagnose the systemd unit (probably wrong `ExecStart` or missing `WorkingDirectory`), patch, run once manually. |
| **Medium** | STCW corpus is 8 years stale (2017-07). MARPOL is 3 years stale (2022-11). USCG MSM is 4 years stale (2021-09). Refresh adapters need to be added to a quarterly timer. | Schedule a corpus-freshness sprint when traffic stabilizes |
| **Medium** | Hybrid BM25 + dense retrieval (RRF fused) is **built and dark-launched** (`HYBRID_RETRIEVAL_ENABLED=False` default). Closes the documented vocab-mismatch failure mode that pure-vector misses. | Set `HYBRID_RETRIEVAL_ENABLED=true` in `/opt/RegKnots/.env`, restart `regknots-api`, re-run the eval, compare to the 96.1% baseline. If A-or-A− improves, leave on; if regresses, flip back. ~30 min including eval. |
| **Medium** | The April audit recommended adding an OSHA / 29 CFR 1910 explicit no-cite clause to the chat system prompt — synthesis LLM keeps inventing OSHA citations on occupational-safety questions, citation-verifier strips them, regen fires (~21% of queries). Not yet shipped. | Add to `prompts.py`: *"Do not cite 29 CFR Part 1910 (OSHA) — those regulations are not in your knowledge base. Maritime workplaces are covered by 46 CFR Subchapter V (Marine Occupational Safety) instead."* |
| **Low** | Load Lines convention has only 4 chunks — very thin coverage. | Re-ingest the full convention next quarterly refresh |
| **Low** | Truncation handling is inconsistent across LLM-call surfaces. Chat path bumps `max_tokens` (D6.75); `me.py` paths use a `_salvage_truncated_json` helper. Same problem, different responses. | Adopt the salvage helper everywhere or unify on a common `parse_json_or_salvage` |
| **OK** | Multi-query rewrite, Haiku reranker, source-diversified fetch (26 source groups), identifier regex (UN/CFR/COLREGs/STCW/SOLAS/IMDG/NVIC), synonym + intent expansion, citation oracle, jurisdiction filter, vessel-profile boosts, hedge judging, web fallback cascade. All shipped + on. | Nothing to do |
| **OK** | Embedding model (`text-embedding-3-small`) is current, multilingual-capable. Re-embedding the entire corpus on `text-embedding-3-large` would cost $3.54 + 4× pgvector storage; April audit and this one agree it's not the bottleneck. | Don't upgrade until a concrete failure mode demands it |
| **OK** | Citation accuracy on study tools — the 1 sample post-A5 deploy shows 100% verified (10/10). Need ~7 days of data before drawing a real verification-rate conclusion. | Re-check next week |

### Top 3 RAG opportunities (in effort/impact order)

1. **Flip on hybrid retrieval (small effort, medium impact).** The single highest-leverage change.
2. **Fix the failed weekly-refresh systemd unit (small effort, high impact for trust).** A user citing a stale rule and getting hammered at port-state inspection is a credibility hit.
3. **Add OSHA no-cite prompt clause (tiny effort, real cost impact).** ~21% of chat queries currently regen because the synthesizer invented an OSHA citation.

---

## Section 4 — Infrastructure + ops

**Auditor's calibration:** The box is not on fire today. But the May 1-2 incident window shows the API was OOM-killed and crashloop-restarted **116 times** over 14 days, and you would have lost the database that day with no way to recover. The deploy/smoke scripts shipped today are the right shape. Backups, monitoring, and the shared-tenancy posture are the next gaps.

### Real findings

| Sev | Area | Finding | Fix |
|---|---|---|---|
| **Critical** | **DB backups** | None. RPO=∞, RTO=12+ hours of corpus reingest plus permanent loss of all user data. | TL;DR #3 |
| **Critical** | **External alerting** | Sentry only. The May 1 OOM crashloop ran 9+ hours (04:35–22:56). No SMS/phone path means you'd find out from a customer or the next time you happened to look. | Better Uptime / healthchecks.io free tier, SMS on `/api/health` every 60s |
| **High** | **Service crashloop history** | regknots-api: 116 failures + 1 explicit OOM-kill / 14d. 13 system-wide OOM events / 14d, several killed Celery + ad-hoc Python ingest jobs (the targets are `task=python3` in user sessions — interactive ingest jobs are memory bombs on a 4 GB box with no swap). | (a) `fallocate -l 2G /swapfile && mkswap /swapfile && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab` (15 min). (b) Add `MemoryHigh=1.5G MemoryMax=2G` to `regknots-api` and `regknots-worker` systemd units. |
| **High** | **Shared tenancy with SpiritFlow** | The other tenant on the same 4 GB box can OOM you. Several of the May 1-2 OOMs targeted user sessions on the box, hostname is `spiritflow-prod-01`. | Within 90 days: provision a dedicated $24/mo droplet for SpiritFlow, give RegKnots the whole box. Or hard-isolate via systemd cgroups. |
| **Medium** | **No CI** | `.github/workflows/` doesn't exist. Every fix ships on hand-test alone. | Add `ci.yml`: `pnpm lint` + `tsc --noEmit` + `pytest` on PR. |
| **Medium** | **Caddy cert sprawl** | 50 cert directories in Caddy, many clearly scanner-injected (`webmail.regknots.com`, etc.). Your `/api/domain-check` endpoint must be returning 200 on garbage subdomains. Could trigger Let's Encrypt rate-limit penalties. | Tighten `domain-check` to validate against your real subdomain set. |
| **Medium** | **No security headers** (also flagged in security audit) | `curl -sI https://regknots.com/landing` shows no HSTS, X-Frame-Options, etc. | Add a `header {}` block to the regknots Caddyfile entry |
| **Low** | **Redis persistence off, no `maxmemory`** | 6 keys in production today; risk is low but Celery queue would be lost on Docker restart. | `maxmemory 256mb`, `maxmemory-policy allkeys-lru`, optionally enable AOF |
| **Low** | **Internal services bind 0.0.0.0** | UFW blocks externally. Defense-in-depth only. | `--host 127.0.0.1` in systemd unit ExecStart |
| **OK** | **VPS resources today** | `df -h`: 16% used. `free -h`: 1.5 GB free. Load avg: 0.2. Uptime: 35 days. | Plenty of headroom |
| **OK** | **Postgres health** | PG 16.13 + pgvector. DB size 1528 MB (99% is the regulations table). Clean alembic head 0092. 1 active + 8 idle connections. 1.9M committed xacts, 0 deadlocks. | Healthy |
| **OK** | **Caddy / TLS** | TLS auto-renewing via ACME. Access logs rotate at 100 MiB / 30 days. Routing config is clean. | Healthy |
| **OK** | **Deploy automation (after today)** | `scripts/deploy.sh` + `scripts/smoke.sh` shipped 2026-05-07. Three-stage smoke (HTTP 200, route bundle present in HTML, canary string in JS chunk) catches the stale-build failure mode that hid Phase A3-A5 from us. | Healthy |
| **OK** | **`.env`** | 32 lines, ~25 distinct keys, no obvious sprawl. Last touched 2026-05-05. | (After permission tighten in TL;DR #2) |

### Local-dev parity — At-Risk

- `infra/docker-compose.yml` exists and exactly matches VPS Postgres (`pgvector/pgvector:pg16`) + Redis versions.
- **No README.md at repo root** — first contributor onboarding fails immediately. Addressed below.
- `.env.example` is missing several keys present on prod: `XAI_API_KEY`, `CREW_TIER_ENABLED`, `CREW_TIER_INTERNAL_ONLY`, `RESEND_FROM_EMAIL`, `WEB_FALLBACK_COSINE_THRESHOLD`, `REGKNOTS_DATABASE_SYNC_URL`. **Worse, it uses `REGKNOTS_JWT_SECRET_KEY` (correct) while VPS uses `REGKNOTS_SECRET_KEY` (broken)** — local-dev would actually work with a proper JWT secret while prod has been silently broken; that's how the JWT-default issue went undetected.
- The `ism_supplement` constraint is now in migration 0090 (memory-file note is stale on this).

### Cost posture (unverifiable from the box; requires dashboard access)

Likely wins, in rough order:
1. Confirm Anthropic prompt caching is enabled on the chat synthesis prefix (5-min TTL = 30-60% savings on retrieval-heavy queries).
2. The `XAI_API_KEY` env var is set on prod but I couldn't confirm whether it's used anywhere. Grep the codebase; if unused, drop it.
3. Embeddings (text-embedding-3-small) are cheap; don't worry about moving to local.
4. The 21%-of-chats regen rate (driven by OSHA hallucinations) translates directly to doubled Sonnet cost on those queries. Single-prompt fix in §3.

### Top 5 infra recommendations (leverage-ranked)

1. **Postgres backups** (TL;DR #3, 10 min, prevents total user-data loss).
2. **Swap + service MemoryMax** (15 min, prevents the May 1 incident class).
3. **External alerting on `/api/health`** (1 hr Better Uptime setup, closes the 9-hour-page gap).
4. **Move SpiritFlow to its own droplet** (4-8 hr, $24/mo extra; removes the largest coupling risk before traffic ramps).
5. **CI workflow** (2 hr, locks deploy hygiene now that you have `scripts/deploy.sh`).

---

## Section 5 — Documentation

**Auditor's calibration:** In-code documentation is **strong** (sprint-tagged comments throughout, module docstrings on Python files, sprint-rationale comments on recent frontend work). Sprint audits are detailed when written. **The gap is structural** — there's no README at the repo root, the canonical `PROJECT_STATE.md` says alembic head is 0045 (it's 0092), no `CLAUDE.md`, no architecture overview, no runbook, no glossary, no per-package READMEs.

### Most-impactful gaps

| Sev | Finding | Action |
|---|---|---|
| **High** | **No `README.md`** at repo root. GitHub repo landing page is empty. | Created in this pass — see commit. |
| **High** | **No `CLAUDE.md`** at repo root. Standing rules + corrections live in `docs/PROJECT_STATE.md` and have to be pasted into every fresh Claude session via `chat-bring-up-prompt.md`. | Created in this pass. |
| **High** | **`docs/PROJECT_STATE.md` is critically stale.** Says alembic head is 0045 (actual: 0092). Says corpus is ~42K chunks across 15 sources (actual: ~77K across 50). "Recent shipped work" ends 2026-04-22; actual head is D6.83 (2026-05-07). | Refreshed in this pass. |
| **High** | **`docs/roadmap.md` is critically stale.** Says "Last updated: 2026-04-20 (post-Sprint-C3)"; "Recent sprints" ends at D5.5. Section 1f ("Deploy script") is now SHIPPED. | Rewritten in this pass; old version archived. |
| **Medium** | `docs/sprint-audits/rag-architecture-audit-april-2026.md` doesn't mention hybrid BM25, citation oracle, multi-query rewrite, Haiku reranker, web fallback cascade, query distillation, or jurisdiction priors — all shipped post-2026-04-20. | Add status banner pointing at this audit + a `docs/architecture.md` writeup. |
| **Medium** | `docs/corpus-status.md` is current (2026-04-28) but predates `nmc_exam_bank` (2026-05-07) and 35+ NMC PDFs added in D6.75/D6.76. | Append rows for these in next refresh |
| **Medium** | Missing `docs/architecture.md` (single-page services + data flow), `docs/runbook.md` (deploy, restart, restore, rotate, rollback), `docs/glossary.md` (CFR, COLREGs, MMC, STCW, MSIB, etc.). | Listed in updated roadmap |
| **Medium** | Memory files are stale: vocab-mismatch is fixed, ism_supplement is in migration 0090. | Updated in this pass |
| **Low** | Per-package READMEs missing: `apps/api/README.md`, `apps/web/README.md`, `packages/rag/README.md`, `packages/ingest/README.md` | Listed in updated roadmap |
| **Low** | No `SECURITY.md`, `CONTRIBUTING.md` | Listed in updated roadmap |
| **Low** | `.env.example` line 49 references `docs/stripe-setup.md` which doesn't exist | Cleanup item |
| **Low** | `packages/rag/regknots_rag.egg-info/` is checked in; should be `.gitignore`d | `git rm -r --cached` |
| **OK** | In-code documentation across recently-modified files (`study.py`, `study/page.tsx`, `education/page.tsx`, `retriever.py`) is **excellent**. Sprint-tagged comments are pervasive and pair well with `git log`. | Nothing to do |

---

## Workflow / automation opportunities

A few specific Cowork / agent ideas surfaced in the audits.

| Idea | Effort | Impact |
|---|---|---|
| Cowork weekly retrieval-miss review (read `retrieval_misses` table, group complete-misses by query pattern, recommend synonym/intent additions) | Medium | High — closes the loop that's already manually working |
| Cowork weekly corpus-freshness sentinel (poll source URLs for changes, file an issue when an upstream version bumps) | Medium | Medium — addresses the STCW/MARPOL/MSM stale-source problem before it's stale |
| Cowork weekly hedge-rate report (`hedge_audits` table → top-N hedged topics → recommend prompt or retrieval fix) | Small | Medium — same loop on the synthesis side |
| Daily smoke probe (already exists as `scripts/smoke.sh`; wire to a scheduled GitHub Action against prod) | Small | Medium — content-asserting probes catch silent stale builds |
| `pre-commit` hook: `pnpm lint && tsc --noEmit` on staged files | Small | Low — modest catch; CI is the proper place |

---

## Updated roadmap (next 30 days)

Priority order, reflecting both this audit and the user's "marketing push imminent" framing.

### Now / this week (≤30 min items, mostly the TL;DR)

1. **Rotate JWT secret** (TL;DR #1). 5 min. **Do before marketing traffic.**
2. **Tighten `.env` perms** (TL;DR #2). 30 sec.
3. **Daily Postgres backups** (TL;DR #3). 10 min.
4. **Bump `next` to 15.5.15+** for the DoS CVE. `pnpm up next` in apps/web, then `scripts/deploy.sh`.
5. **Fix the failed `regknots-refresh-weekly.service`.** 5 days dead. ~15 min.
6. **Update memory files** (vocab-mismatch and ism_supplement are both resolved). Done in this pass.

### Next 1-2 weeks (real iterations)

7. **Flip on hybrid BM25+dense retrieval** behind the existing `HYBRID_RETRIEVAL_ENABLED` flag, eval, decide. ~30 min.
8. **Add OSHA no-cite clause** to chat system prompt. 30 min.
9. **External alerting** (Better Uptime / healthchecks.io). ~1 hr.
10. **2 GB swap + per-service `MemoryMax`** on systemd units. ~15 min.
11. **CI workflow** (`pnpm lint`, `tsc`, `pytest` on PR). ~2 hr.
12. **First three tests** (Stripe webhook, study shuffler, retriever identifier extractors). ~3 hr total.
13. **Extract `app/llm_helpers.py`** + collapse the 6 me.py duplicates. ~3 hr.
14. **Caddy security headers + rate limit on `/api/domain-check`**. ~30 min.
15. **Fix Sentry frontend env tag**. 5 min.

### Within 30 days (architectural)

16. **Move SpiritFlow to its own droplet** — removes the largest coupling risk before traffic ramps. $24/mo + ~6 hr.
17. **Sprint of test coverage** for auth + billing + Sonnet endpoints. ~2 days.
18. **Documentation completion** per the gap list above (architecture.md, runbook.md, glossary.md, per-package READMEs, SECURITY.md, CONTRIBUTING.md). ~6 hr.
19. **Off-host backup destination** (B2/S3 nightly upload). ~1 hr.

### Deferred / re-check next quarter

- Embedding upgrade to `text-embedding-3-large` (April + this audit agree it's not the bottleneck).
- Hot-replica Postgres (overkill at current scale).
- STCW + MARPOL + MSM corpus refresh (schedule a focused sprint when traffic stabilizes).
- Remove all `'use client'` from marketing landing pages → RSC + client islands (cumulative bundle hit; not blocking).

---

## Verdict matrix

| Domain | Status |
|---|---|
| Security | At-Risk → Healthy after TL;DR #1 + #2 |
| Code quality / type safety | OK |
| Test coverage | At-Risk |
| RAG retrieval | Healthy |
| Corpus health | Healthy (3 stale outliers, 1 broken refresh job) |
| Infrastructure (today) | Healthy |
| Infrastructure (resilience) | At-Risk → Healthy after TL;DR #3 + alerting |
| Backups + DR | **Critical** until TL;DR #3 |
| Monitoring | At-Risk |
| Deploy hygiene | Healthy (after 2026-05-07) |
| Documentation structure | At-Risk → Improved by this pass |
| Documentation in-code | Healthy |

**Going-away-for-two-days probability matrix:**

- "Everything's fine when you come back": high. The box has been quiet since the last OOM event 5+ days ago, services restarted cleanly at 23:25 UTC, no current pressure on disk/RAM.
- "Something interesting happened that needs attention": medium. The Sentry uptime check will email if a key route 5xx-s.
- "Disaster scenario": low but **unbounded recovery cost without TL;DR #3.** A 10-minute backup setup before you walk away cuts the worst case from "lose everything" to "lose ≤24h of activity."

If you do nothing else from this audit, do TL;DR #1 (JWT) and #3 (backups). Ten minutes total. Sleep better.

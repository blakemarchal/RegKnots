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

## What was just done (last 14 days, headline only)

- D6.83 Sprint A1-A5: Study Tools — quiz + study guide generators, take-the-quiz mode, citation verification, PDF export. NMC exam-bank ingest (244 sections / 2,938 chunks).
- D6.83 Sprint B: `/education` landing page, persona pre-set on signup, `cadet_student`/`teacher_instructor` post-onboarding redirect to `/study`.
- D6.83 Account toggle: `users.study_tools_enabled`, hidden from nav when off.
- 2026-05-07: `scripts/deploy.sh` + `scripts/smoke.sh` shipped — closes the "no auto-deploy" gap; smoke probes are content-asserting (HTTP 200 + JS-chunk canary string), not status-only.
- 2026-05-08: full-system audit at `docs/sprint-audits/full-system-audit-2026-05-08.md`. Two critical-but-fixable findings (JWT secret env-var mismatch, no DB backups) flagged for pre-marketing-push fix.
- 2026-05-09 D6.84 Sprint A: confidence tier router shipped in **shadow mode** on prod. Adds 4-tier provenance (✓ Verified / ⚓ Industry Standard / 🌐 Relaxed Web / ⚠ Best-effort) on top of today's pipeline. Closes the partial_miss-low-web dead zone where Jordan Dusek's gasket-class questions hedged. Flag: `CONFIDENCE_TIERS_MODE=off|shadow|live`. Migration 0093 adds `tier_router_shadow_log` table + `messages.tier_metadata` JSONB. Admin compare view at `/admin/tier-router`. 12/12 unit tests pass. Gold set at `data/eval/tier_router_gold.json`. **Phase E flip to `live` is operator-driven.**

See `docs/PROJECT_STATE.md` for a fuller operational snapshot and `docs/roadmap.md` for the prioritized backlog.

## Known issues (2026-05-08)

The audit caught two memory items as **stale** — both are actually resolved:

- **Vocab mismatch** (memory said: "no fix yet"): SHIPPED. `packages/rag/rag/synonyms.py` has lifejacket→lifesaving-appliance, log→logbook, mob, stability, stencil/stenciled/stenciling. `packages/rag/rag/query_rewrite.py` produces 2-3 reformulations every chat (default ON). Two intent expanders fire on dual-signal gates.
- **`ism_supplement` migration drift** (memory said: "added live, not in migration files"): RESOLVED. Migration `0090_add_nmc_exam_bank_source.py` defines the canonical source list including `ism_supplement`.

Real open items (see audit + roadmap for the full list):

- JWT signing key — VPS `.env` has wrong env var name; falls back to default. **Pre-marketing fix.**
- `.env` permissions on prod are 0644. **Pre-marketing fix.**
- Zero DB backups exist. **Pre-marketing fix.**
- `regknots-refresh-weekly.service` failed 2026-05-03 with exit 203 (EXEC). 5 days dead.
- Zero test coverage anywhere.
- LLM-helper boilerplate copy-pasted 6× in `apps/api/app/routers/me.py`.

## Pointers

- **Operational state:** `docs/PROJECT_STATE.md`
- **Strategic roadmap:** `docs/roadmap.md`
- **Latest full audit:** `docs/sprint-audits/full-system-audit-2026-05-08.md`
- **Corpus inventory:** `docs/corpus-status.md`
- **Scaling thresholds:** `docs/scaling-roadmap.md`
- **Cowork tasks:** `docs/cowork-task-prompts.md`
- **Long-form bring-up (deeper):** `docs/chat-bring-up-prompt.md`

---

*Last updated 2026-05-09 (post-D6.84 Sprint A — tier router shadow). When this drifts from reality, fix it — that's the rule.*

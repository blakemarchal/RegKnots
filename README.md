# RegKnots

Maritime-compliance copilot for U.S. commercial vessel operators. Live at https://regknots.com.

Built by **Karynn Marchal** (CEO, USCG Master Unlimited, active containership Captain) and **Blake Marchal** (CTO, engineer).

What it does: answers maritime regulatory questions with verified citations from real CFR/SOLAS/COLREGs/STCW/MARPOL/ISM source text — no hallucinated regulations, no "consult an attorney" hand-waves. Vessel-aware, credential-aware, and audit-ready. Plus a Study Tools product (quizzes + study guides) for USCG mariner exam prep.

---

## Stack

| Layer | Tech | Where |
|---|---|---|
| API | FastAPI (Python 3.12, [uv](https://docs.astral.sh/uv/)) | `apps/api/` |
| Web | Next.js 15 + React 19 (TypeScript, Turbopack) | `apps/web/` |
| DB | Postgres 16 + [pgvector](https://github.com/pgvector/pgvector) HNSW (Docker) | `infra/docker-compose.yml` |
| Worker | Celery + Redis | `apps/api/app/worker/` |
| Reverse proxy | Caddy (TLS via ACME) | VPS `/etc/caddy/` |
| RAG | Claude Haiku/Sonnet/Opus router + OpenAI text-embedding-3-small | `packages/rag/` |
| Ingest | per-source adapters (CFR, NVIC, NMC, USCG bulletins, IMO, flag-state) | `packages/ingest/` |
| Auth | JWT (HS256, 15-min access, 7-day rotating refresh) + Argon2 hashing | `apps/api/app/auth/` |
| Billing | Stripe (Mate $14.99/mo promo, Captain $29.99/mo promo, Wheelhouse $99.99/mo) | `apps/api/app/stripe_service.py` |
| Errors / monitoring | Sentry (api + web) | `apps/api/app/main.py`, `apps/web/src/instrumentation*.ts` |

The corpus today: **~77,000 chunks across 50 sources** (CFR 33/46/49, COLREGs, SOLAS, STCW, MARPOL, ISM, IMDG, ERG, NVIC, USCG MSM, USCG bulletins, NMC policy/checklists/exam-bank, plus 13 flag-state corpora). 100% embedding coverage. Eval baseline: **96.1% A-or-A−** on a 152-question regression suite (April 2026). See [`docs/corpus-status.md`](docs/corpus-status.md).

---

## Quick start

Prereqs: Node 20+, pnpm 9+, Python 3.12, [uv](https://docs.astral.sh/uv/), Docker, an OpenAI API key, and an Anthropic API key.

```bash
# 1. Configure
cp .env.example .env
# Edit .env: set OPENAI_API_KEY, ANTHROPIC_API_KEY, REGKNOTS_JWT_SECRET_KEY (any 32+ char random).
# Stripe keys are optional locally — billing endpoints will return 503 without them, which is fine for dev.

# 2. Spin up Postgres + Redis
pnpm infra:up

# 3. Install JS deps
pnpm install

# 4. Start the API (port 8000). Auto-runs `alembic upgrade head` on first start.
pnpm dev:api

# 5. In another shell, start the web app (port 3000).
pnpm dev:web

# Visit http://localhost:3000
```

`pnpm infra:down` to stop the Docker stack. The Postgres volume `pgdata` persists between runs.

There is no plain `pnpm dev` — the api and web servers run independently in their own terminals.

The web build sets `NEXT_PUBLIC_API_URL` at build time and hard-fails the build if it's not present. For prod builds: `NEXT_PUBLIC_API_URL=https://regknots.com/api pnpm build:web`.

---

## Layout

```
apps/
  api/              # FastAPI service. Routers in app/routers/. Alembic migrations at apps/api/alembic/versions/ (head: 0092).
  web/              # Next.js 15 app router. 30+ routes under src/app/.

packages/
  rag/              # Retrieval, router, synthesis, citation oracle, hedge judge, web fallback.
  ingest/           # Corpus adapters, chunker, embedder, dispatcher CLI.

infra/
  docker-compose.yml    # Postgres + Redis. The api/web/worker run on the host.
  systemd/              # Production unit files (corpus refresh timers, etc.)

scripts/
  deploy.sh         # SSH → pull → alembic → pnpm build → systemctl restart → smoke. Run from your laptop.
  smoke.sh          # Content-asserting probes against prod (HTTP 200 + JS-chunk canary string).
  eval_rag_baseline.py
  ...               # Ingest helpers, OCR, brand-asset generators, etc.

docs/
  PROJECT_STATE.md  # Operational snapshot: alembic head, corpus, recent sprints, standing rules.
  roadmap.md        # Strategic roadmap.
  scaling-roadmap.md
  sprint-audits/    # Architecture audits + the latest full-system audit.
  testing/          # Test plans (regression, crew tier).

data/
  raw/              # Source PDFs / HTML for ingest. Cowork writes here only.
  eval/             # Regression-eval outputs.
  uploads/          # User-uploaded vessel docs / credential photos (production-only path).
```

---

## Workflow

```bash
# Run the corpus ingest CLI
pnpm ingest --source cfr_46 --year 2026

# Run the regression eval
python scripts/eval_rag_baseline.py

# Lint + type-check the web app
pnpm lint:web
cd apps/web && npx tsc --noEmit

# Deploy to production (after pushing to main)
scripts/deploy.sh

# Smoke-test production without deploying
scripts/smoke.sh
```

---

## Where to look next

- **Operational snapshot** (alembic head, corpus inventory, recent sprints, standing rules): [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md)
- **Strategic roadmap** (now / 1-2 weeks / 30 days / deferred): [`docs/roadmap.md`](docs/roadmap.md)
- **Latest full-system audit**: [`docs/sprint-audits/full-system-audit-2026-05-08.md`](docs/sprint-audits/full-system-audit-2026-05-08.md)
- **Corpus inventory + freshness**: [`docs/corpus-status.md`](docs/corpus-status.md)
- **Bringing up a new Claude session**: [`docs/chat-bring-up-prompt.md`](docs/chat-bring-up-prompt.md)
- **Scaling thresholds**: [`docs/scaling-roadmap.md`](docs/scaling-roadmap.md)

---

## Standing rules (excerpt)

The full set lives in [`docs/PROJECT_STATE.md`](docs/PROJECT_STATE.md). Highlights:

- Production deploys come from `origin/main` via `scripts/deploy.sh`. Never edit on the VPS.
- Schema-first: every DB change goes through an Alembic migration. The current head is `0092`.
- New features start with a written spec — propose, get a greenlight, then implement.
- Karynn (the CEO) is `kdmarchal@gmail.com`. She's `is_admin` but not Owner.
- The shipping CLI (`packages/ingest/ingest/cli.py`) has a `dsn.replace(...)` shim that must not be regenerated by codegen tools.

---

## Status

**Production (VPS):** healthy. Alembic at head 0092. Last deploy: see `git log origin/main`.

**Marketing posture:** Sprint D6.83 just shipped (Study Tools, `/education` landing, account toggle, deploy automation). Gearing up for a marketing push — see the audit doc for the pre-launch checklist.

---

License: proprietary. Not currently accepting external contributions.

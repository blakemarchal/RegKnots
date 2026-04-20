# RegKnot — Chat Bring-Up Prompt

Paste this at the start of a fresh Claude.ai / Claude Desktop session when you want the model to work on RegKnot with full context. Works equally well for Cowork sessions.

---

## Short form (copy/paste into chat)

```
Context: RegKnot — maritime-compliance RAG at https://regknots.com.
Repo: C:\Users\Blake Marchal\Documents\RegKnots (local), /opt/RegKnots (VPS: root@68.183.130.3).

Read these in order before responding:
1. docs/PROJECT_STATE.md — one-page snapshot (corpus, pipeline, eval progression, known issues, standing rules). ALWAYS start here.
2. docs/roadmap.md — full strategic roadmap if the task touches priorities or sequencing.
3. Task-specific docs (only if relevant): docs/sprint-audits/rag-architecture-audit-april-2026.md, docs/testing/retrieval-regression-test-plan.md.

Standing rules (non-negotiable, also in PROJECT_STATE.md):
- Branch policy: commit directly to main; merge worktree → main at end of every task; I push manually.
- Sister's name is Karynn (CEO, Unlimited Licensed Captain). NEVER write "Cassandra" — grep before every commit.
- Owner email is blakemarchal@gmail.com (hardcoded in apps/api/app/routers/admin.py). Karynn is is_admin but not Owner.
- Do NOT regenerate packages/ingest/ingest/cli.py — patch in place; preserve the dsn replace("postgresql+asyncpg://", "postgresql://") line at create_pool.
- Schema-first: read the actual DB schema before writing queries.
- Propose spec, wait for greenlight before coding non-trivial work.

Ask me for the task. No other briefing needed.
```

---

## Long form (when the model needs the full pitch)

```
RegKnot is a maritime-compliance RAG co-pilot for U.S. commercial vessel
operators — live at https://regknots.com. Built by Blake Marchal
(engineer) and Karynn Marchal (CEO, Unlimited Licensed Captain). Corpus
is ~42K chunks across 15 sources (CFR 33/46/49, SOLAS, STCW, ISM,
COLREGs, ERG, NVICs, NMC policy + checklists, USCG bulletins).

Tech stack: Python, FastAPI, Postgres + pgvector HNSW, Next.js web,
Claude Haiku/Sonnet/Opus routed by query complexity, OpenAI
text-embedding-3-small, Celery + Redis.

Current quality bar: Sprint C3 regression eval holds 100% A across 28
queries × 5 vessel profiles. Sprint C2 introduced a vessel-type ×
CFR-Subchapter applicability filter that structurally solves the "wrong
Subchapter" citation bug. We are waiting on Karynn's exhaustive test
pass (10-vessel, ~60-question bank) before re-engaging lapsed pilots.

Working-directory conventions:
- Local: C:\Users\Blake Marchal\Documents\RegKnots
- VPS: /opt/RegKnots on root@68.183.130.3 (NOT /root/RegKnots)
- Alembic head: 0045
- Services: regknots-api, regknots-web, regknots-worker (all systemd, all active)

Primary docs:
- docs/PROJECT_STATE.md — READ FIRST. One-page operational snapshot.
- docs/roadmap.md — strategic roadmap with priority tiers 1-3.
- docs/sprint-audits/ — deep-dive audits per sprint.
- docs/testing/retrieval-regression-test-plan.md — pilot test bank.

Standing rules:
- Branch policy: commit directly to main; merge worktree → main at end
  of every task; Blake pushes manually.
- Sister's name is Karynn. NEVER "Cassandra" — grep before every commit.
- Owner email blakemarchal@gmail.com hardcoded in admin router.
- packages/ingest/ingest/cli.py: patch in place, never regenerate;
  preserve the dsn replace() line at create_pool.
- Schema-first: read actual DB schema before writing queries.
- Propose spec, wait for greenlight before coding non-trivial work.

Ask me for the task.
```

---

## Using with Cowork

Cowork lets Claude operate across chat, your IDE, and sometimes the browser/terminal on a task. When starting a Cowork session on RegKnot:

1. Paste the **short form** above as the first message.
2. If the task touches the VPS or live production, explicitly tell Cowork it may ssh into `root@68.183.130.3` and that `/opt/RegKnots` is the production repo path.
3. If the task is UI-adjacent, point at `apps/web/` (Next.js).
4. If it's ingest/RAG, point at `packages/rag/` and `packages/ingest/`.
5. Remind it that docs go in `docs/` and scripts in `scripts/`.

Cowork is especially useful for RegKnot tasks that span:
- Code edit (IDE) + eval run (terminal on VPS) + result review (chat)
- Corpus inspection (DB query via ssh) + prompt tuning (file edit) + regression re-run

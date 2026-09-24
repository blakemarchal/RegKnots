# Postgres `shared_buffers` 128 MB → 512 MB — spec

**Status:** awaiting Blake's go (restarts prod Postgres; ~10–30 s of failed requests).
**Date:** 2026-09-23. **Asked for by:** Blake ("go with shared_buffers, spec it").
**Evidence:** read-only diagnostics on prod, 2026-09-23 20:10 UTC (`free`, `/proc`, `docker inspect`, `pg_settings`, `pg_statio_*`, and `EXPLAIN (ANALYZE, BUFFERS)` of the exact `_fetch_group` SQL for every source group).

---

## 1. Why

Retrieval runs one vector query per source group — 31 groups, 4 times per question (once per rewrite) — before synthesis can start. Measured on one real question with a US-flag profile:

| Run | 31 group queries | Read from outside `shared_buffers` |
|---|---|---|
| As resident now, sequential | 3.0 s | 13,651 blocks (107 MB) |
| Warm, sequential | 0.47 s | 4,065 blocks (32 MB) |
| Concurrent like `retrieve()`, 3 back-to-back runs | 0.93 s, 2.19 s, 2.51 s | — |

- **21 of 31 groups never touch the HNSW index.** They are small (100–2,000 rows), so the planner filters by source and jurisdiction and computes exact distances. That reads every embedding in the group, and each 6 KB embedding lives in TOAST. This is correct planner behavior, but it is where the I/O comes from.
- **One question touches ~720 MB of buffers** (92,700 accesses, pass 1), through a 128 MB pool. Even warm, 32 MB per pass comes from outside the pool. Running concurrently, the queries evict each other, which is why the fan-out gets slower on repeated runs instead of faster.
- **The pool is the image default.** `shared_buffers = 128 MB` from the stock `postgresql.conf`. `infra/docker-compose.yml` sets nothing, and Postgres has not restarted since 2026-04-04.
- **Lifetime hit ratios:** HNSW index 97.6%, heap 82%, TOAST 62%. TOAST reads are 90 M blocks.
- **Deploys make it worse.** On the first question after today's 19:50 UTC deploy, the DB phase took ~12.7 s against ~2 s warm. Postgres did not restart; the `pnpm build` pushed the data out of the OS page cache. Swap confirms builds create memory pressure: ~410 MB of the Next.js server sits in swap today.

## 2. What this fixes, and what it does not

The data a question needs is small enough to keep in Postgres's own memory:

| Working set | Size |
|---|---|
| Exact-scan groups for a US-flag question (~10,000 rows) | ~60 MB of embeddings + ~30 MB text and heap |
| All flags' exact-scan groups (~16,800 rows) | ~100 MB of embeddings + text |
| HNSW pages touched per search | ~544 buffers (4 MB); upper layers are shared across searches |
| HNSW index, whole | 828 MB (does not fit; not needed) |

**Expected:**

| | Today | Expected at 512 MB |
|---|---|---|
| DB part of retrieval, warm | ~0.5–2.5 s | ~0.4–1 s (the rest is CPU: distance math and sorting on 2 cores) |
| DB part, first question after a deploy | ~12.7 s | ≈ warm; the build can no longer evict the working set |
| Whole pre-synthesis wait, warm | ~8.4 s | ~7–7.5 s |
| Whole pre-synthesis wait, after a deploy | ~19 s | ~8 s |

**Not fixed here:** the Haiku rewrite (~1.5–2 s) and rerank (~3–4.5 s) are now most of the warm wait, and they are the next latency lever. `shared_buffers` is not a planner input, so query plans — and therefore retrieval results — do not change (verified in §5).

## 3. Proposal

1. `shared_buffers = 512MB` (from 128 MB). `wal_buffers` auto-scales from 4 MB to 16 MB with it.
2. `shared_preload_libraries = 'pg_prewarm'`. Its autoprewarm worker records what is in the pool every 5 minutes and reloads it after a restart, so a future reboot or image update does not start cold. It needs a restart to load, and this change restarts anyway.
3. `CREATE EXTENSION pg_buffercache` (a read-only view) to verify what the pool holds after the change. Both extensions ship in the image and are listed as available on prod.
4. **Unchanged, on purpose:** `effective_cache_size` (still the 4 GB default, which overstates the box), `work_mem`, `max_connections`, `random_page_cost`. Changing those would change plans and needs the retrieval harness. This spec is plan-neutral.

In `infra/docker-compose.yml` (the container belongs to compose project `infra` in `/opt/RegKnots/infra`, so config lives in the repo):

```yaml
  postgres:
    image: pgvector/pgvector:pg16
    # 2026-09-23 — see docs/postgres-shared-buffers-spec-2026-09-23.md
    command: ["postgres", "-c", "shared_buffers=512MB", "-c", "shared_preload_libraries=pg_prewarm"]
```

## 4. Memory budget (box: 2 vCPU, 3.9 GB RAM, 2 GB swap, swappiness 10)

| | Today | At 512 MB | At 1 GB (not recommended) |
|---|---|---|---|
| Processes in use | 1,366 MB | ~1,750 MB | ~2,270 MB |
| Available for page cache and builds | 2,549 MB | ~2,170 MB | ~1,650 MB |

Top processes: Next.js server 400 MB, Postgres 347 MB, Celery 226 MB, uvicorn 172 MB, Caddy 66 MB. The `merch-postgres` and `merch-redis` containers on the same box are capped at 768 MB and 192 MB. There were no OOM kills in the last 30 days.

512 MB holds the whole exact-scan working set for every flag, plus a large share of the HNSW hot pages, and leaves room for `pnpm build`. At 1 GB a build would squeeze the page cache to nearly nothing and push more to swap. 768 MB is the step up if §5's pool check shows 512 MB full with a hit ratio under 99% after a week.

## 5. Procedure

Pre-checks, read-only:

1. **Image unchanged.** `docker inspect regknots-postgres --format '{{.Image}}'` must equal `docker image inspect pgvector/pgvector:pg16 --format '{{.Id}}'`. If the tag has moved, pin the running image's digest in the compose file for this change, so the restart is not also a pgvector upgrade.
2. **Compose command matches.** `docker compose version` works, and `docker compose -f /opt/RegKnots/infra/docker-compose.yml config` shows only the new `command`.
3. **Baselines.** Record `free -m`, `vmstat 1 5`, and the EXPLAIN diagnostic.

Change, in a low-traffic window:

4. Commit the compose change, push, then `scripts/deploy.sh`. This puts the file on the VPS; it does not touch Postgres.
5. Recreate the container from the laptop in one SSH command:
   `cd /opt/RegKnots/infra && docker compose up -d --no-deps postgres`
   The data volume `infra_pgdata` is kept. Shutdown checkpoint plus startup takes ~10–30 s, and requests during that window fail.
6. Wait for the healthcheck, then run `systemctl restart regknots-api regknots-worker` so the connection pools start fresh. Then run `scripts/smoke.sh`.
7. Run `SHOW shared_buffers;` (expect `512MB`) and `SHOW shared_preload_libraries;` (expect `pg_prewarm`), then `CREATE EXTENSION IF NOT EXISTS pg_buffercache;`.

Verify:

8. **Warm-up and speed.** Run the EXPLAIN diagnostic twice. The first run warms the pool. On the second, expect about 0 blocks read from outside the pool, and three concurrent fan-out runs that stay flat at about 1 s or less.
9. **Plans unchanged.** `scripts/eval_retrieval.py --arm dense` must return exactly 0.8226 / 0.6881, the same per-pair ranks as the 2026-09-23 run.
10. **Pool contents.** Check what the pool holds: `SELECT c.relname, count(*) * 8 / 1024 AS mb FROM pg_buffercache b JOIN pg_class c ON b.relfilenode = pg_relation_filenode(c.oid) GROUP BY 1 ORDER BY 2 DESC LIMIT 10;`
11. **Next deploy.** Watch `vmstat` swap-in and swap-out during the build. Time the first chat question afterwards; it should be close to warm.
12. **After a week.** Recheck the `pg_statio` hit ratios. Reset the counters on change day with `pg_stat_reset()`, so the numbers are not five months of history.

## 6. Rollback

Revert the compose `command`, then repeat steps 4–6. That is another ~10–30 s restart with no data change. If Postgres fails to start with the new flags, for example a preload problem, the same revert applies; the data directory is untouched.

## 7. Decisions for Blake

1. **Value:** 512 MB (recommended), or 768 MB.
2. **Autoprewarm:** include `pg_prewarm` in the same restart (recommended).
3. **Window:** when to take the ~10–30 s restart. Traffic is low at any hour right now.
4. **`pg_buffercache`:** OK to create it for verification (read-only).

## 8. Not in this spec

- **Store embeddings inline.** Using `halfvec`, or `SET STORAGE PLAIN` with a table rewrite, would remove the TOAST lookups behind the exact scans. It is the structural fix, but high-risk: it rewrites a 2.3 GB table.
- **Trim the source-group fan-out.** This is retrieval-changing and needs the harness.
- **Rerank and rewrite latency** (~5–6 s of Haiku). This is the next latency item after this one.
- **`effective_cache_size`.** Right-sizing it to the real cache (about 2 GB) is a planner change and needs the harness.

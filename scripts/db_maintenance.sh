#!/usr/bin/env bash
# scripts/db_maintenance.sh — weekly Postgres upkeep for RegKnots.
#
# 2026-07-19 — created alongside removing the per-ingest full REINDEX
# from packages/ingest/ingest/cli.py. That REINDEX took an ACCESS
# EXCLUSIVE lock on idx_regulations_embedding (blocking every live chat
# retrieval for the rebuild duration) to freshen a few hundred chunks.
# pgvector maintains the HNSW graph incrementally on writes; the only
# real reason to periodically rebuild is graph-quality decay after
# sustained churn (deleted tuples leave ghost nodes). Weekly CONCURRENTLY
# does that with zero lock contention.
#
# Invoked by regknots-db-maintenance.timer (deploy/systemd/), Sundays
# 04:30 UTC — after the 03:00 backup and the 03:36 weekly corpus refresh
# so we compact whatever the refresh churned.
#
# What it does:
#   1. REINDEX INDEX CONCURRENTLY idx_regulations_embedding
#      (no lock; leaves an _ccnew invalid index behind ONLY on failure —
#      we detect and drop it so a crashed run can't strand one).
#   2. VACUUM (ANALYZE) regulations — reclaim dead tuples from ingest
#      churn, refresh planner stats for the retrieval SQL.
#   3. Backup staleness gate — newest dump in /var/backups/regknots must
#      be < 26h old, else exit non-zero so the unit shows failed.
#
# Env overrides: PG_CONTAINER, PG_USER, PG_DB, BACKUP_DIR as in
# backup_postgres.sh.

set -euo pipefail

readonly PG_CONTAINER="${PG_CONTAINER:-regknots-postgres}"
readonly PG_USER="${PG_USER:-regknots}"
readonly PG_DB="${PG_DB:-regknots}"
readonly BACKUP_DIR="${BACKUP_DIR:-/var/backups/regknots}"

psql_exec() {
    docker exec "$PG_CONTAINER" psql -U "$PG_USER" -d "$PG_DB" -v ON_ERROR_STOP=1 -tAc "$1"
}

echo "[$(date -u +%FT%TZ)] db-maintenance start"

# ── 1. HNSW reindex, concurrently ───────────────────────────────────────
# A failed CONCURRENTLY leaves an INVALID index named *_ccnew; drop any
# stragglers from a previous crashed run before starting a new one.
stale_ccnew="$(psql_exec "SELECT indexrelid::regclass::text FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE NOT i.indisvalid AND c.relname LIKE 'idx_regulations_embedding%'" || true)"
if [[ -n "$stale_ccnew" ]]; then
    echo "dropping stranded invalid index from prior failed run: $stale_ccnew"
    psql_exec "DROP INDEX CONCURRENTLY IF EXISTS ${stale_ccnew}"
fi

t0=$(date +%s)
psql_exec "REINDEX INDEX CONCURRENTLY idx_regulations_embedding"
echo "[$(date -u +%FT%TZ)] HNSW reindex done in $(( $(date +%s) - t0 ))s"

# ── 2. Vacuum + stats ───────────────────────────────────────────────────
t0=$(date +%s)
psql_exec "VACUUM (ANALYZE) regulations"
echo "[$(date -u +%FT%TZ)] vacuum-analyze done in $(( $(date +%s) - t0 ))s"

# ── 3. Backup staleness gate ────────────────────────────────────────────
# The backup timer runs daily at 03:00. If the newest dump is older than
# 26h, the backup pipeline is silently broken — fail this unit loudly so
# `systemctl --failed` / journal reviews catch it. (Also probed from the
# laptop by scripts/smoke.sh after every deploy.)
newest="$(find "$BACKUP_DIR" -maxdepth 1 -name 'regknots-*.sql.gz' -mmin -1560 | head -1)"
if [[ -z "$newest" ]]; then
    echo "ERROR: no backup newer than 26h in ${BACKUP_DIR} — backup pipeline is broken" >&2
    exit 4
fi
echo "[$(date -u +%FT%TZ)] backup freshness OK ($(basename "$newest"))"

echo "[$(date -u +%FT%TZ)] db-maintenance complete"

#!/usr/bin/env bash
# scripts/backup_postgres.sh — daily Postgres backup for RegKnots.
#
# Invoked by the regknots-backup.service systemd unit (deploy/systemd/).
# Can also be run manually for an ad-hoc snapshot:
#
#   sudo /opt/RegKnots/scripts/backup_postgres.sh
#
# What it does:
#   1. pg_dump from inside the running regknots-postgres docker container
#      (uses the container's bundled pg_dump for guaranteed version match
#      against the live server). Plain SQL format, gzipped.
#   2. Writes to /var/backups/regknots/regknots-YYYYMMDD-HHMMSS.sql.gz.
#   3. Verifies gzip integrity + sanity-checks the dump contains the
#      expected schema (a known table name) before declaring success.
#   4. Prunes backups older than ${RETENTION_DAYS:-14} days.
#
# Exits non-zero on any failure so systemd marks the unit failed (and a
# journalctl tail or external alerter sees it).
#
# Env overrides:
#   BACKUP_DIR        default /var/backups/regknots
#   RETENTION_DAYS    default 14
#   PG_CONTAINER      default regknots-postgres
#   PG_USER           default regknots
#   PG_DB             default regknots

set -euo pipefail

readonly BACKUP_DIR="${BACKUP_DIR:-/var/backups/regknots}"
readonly RETENTION_DAYS="${RETENTION_DAYS:-14}"
readonly PG_CONTAINER="${PG_CONTAINER:-regknots-postgres}"
readonly PG_USER="${PG_USER:-regknots}"
readonly PG_DB="${PG_DB:-regknots}"

readonly TS="$(date -u +%Y%m%d-%H%M%S)"
readonly OUT_FILE="${BACKUP_DIR}/regknots-${TS}.sql.gz"

mkdir -p "$BACKUP_DIR"
chmod 750 "$BACKUP_DIR"

echo "[$(date -u +%FT%TZ)] backing up ${PG_DB} from ${PG_CONTAINER} → ${OUT_FILE}"

# Compressor: prefer pigz (parallel gzip) when available, fall back to gzip.
# Use level 3 (was 9). gzip -9 was single-threaded + CPU-bound on the
# embeddings column and ran past the 15-min systemd timeout (~14m+ CPU).
# pigz -3 on 2 cores cuts wall time ~5x at the cost of ~5-10% larger files.
# That's a great trade for nightly backups.
if command -v pigz >/dev/null 2>&1; then
    COMPRESSOR=(pigz -3)
else
    COMPRESSOR=(gzip -3)
fi

# Stream pg_dump output through the compressor directly into the
# destination file. Pipefail catches a pg_dump or compressor non-zero
# anywhere in the pipeline.
docker exec "$PG_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" \
    | "${COMPRESSOR[@]}" > "$OUT_FILE"

# Lock down the file: only root can read this — it contains every secret-
# adjacent value in the DB (refresh_tokens hashes, hashed passwords).
chmod 600 "$OUT_FILE"

# Sanity check 1: gzip integrity.
if ! gzip -t "$OUT_FILE"; then
    echo "ERROR: gzip integrity check failed for $OUT_FILE" >&2
    rm -f "$OUT_FILE"
    exit 2
fi

# Sanity check 2: dump contains expected schema. The 'regulations' table
# has been around since the very first migration; if it's absent, the dump
# is wrong (empty DB? wrong DB?).
#
# This check is fiddly because of pipefail: any decompress-then-match
# pipeline (gunzip | grep, zgrep, zcat | grep) makes grep short-circuit
# on first match, SIGPIPE the decompressor, the decompressor exits
# non-zero, pipefail catches it as a pipeline failure, valid backup
# gets deleted. We sidestep by:
#   1. Running the check in a subshell with pipefail OFF.
#   2. Capping decompression to the first 5MB via head — pg_dump emits
#      all CREATE TABLE statements at the very top of the file, well
#      before any data rows.
if ! ( set +o pipefail; gunzip -c "$OUT_FILE" 2>/dev/null | head -c 5000000 | grep -qm1 'TABLE.*regulations' ); then
    echo "ERROR: dump does not contain expected 'regulations' table — bad dump?" >&2
    rm -f "$OUT_FILE"
    exit 3
fi

size_bytes="$(stat -c '%s' "$OUT_FILE")"
size_human="$(numfmt --to=iec --suffix=B "$size_bytes" 2>/dev/null || echo "${size_bytes}B")"
echo "[$(date -u +%FT%TZ)] backup OK · size=${size_human} · path=${OUT_FILE}"

# Retention prune. -mtime +N matches files older than N*24h.
pruned="$(find "$BACKUP_DIR" -maxdepth 1 -name 'regknots-*.sql.gz' -mtime "+${RETENTION_DAYS}" -print -delete | wc -l || true)"
if [[ "$pruned" -gt 0 ]]; then
    echo "[$(date -u +%FT%TZ)] pruned ${pruned} backup(s) older than ${RETENTION_DAYS} days"
fi

# Summary footer for the journal.
total_backups="$(find "$BACKUP_DIR" -maxdepth 1 -name 'regknots-*.sql.gz' -printf . | wc -c)"
total_bytes="$(du -sb "$BACKUP_DIR" 2>/dev/null | awk '{print $1}')"
total_human="$(numfmt --to=iec --suffix=B "$total_bytes" 2>/dev/null || echo "${total_bytes}B")"
echo "[$(date -u +%FT%TZ)] backup-dir summary · count=${total_backups} · total=${total_human}"

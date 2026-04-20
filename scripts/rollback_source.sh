#!/usr/bin/env bash
# rollback_source.sh — undo a corpus ingest cleanly.
#
# Usage:   scripts/rollback_source.sh <source> [hours]
#
# Deletes every regulations row for <source> and deactivates any
# regulation_update notifications for the same source created within the
# last <hours> hours (default 24). Runs as a single transaction so the
# notifications panel and the corpus never end up in inconsistent states
# (the Sprint B → B2 rollback hit that exact bug — 3,482 rows gone but
# the "3482 new sections" banner stayed active for a day).
#
# The rollback window is intentionally bounded. Older notifications for
# the same source are preserved as history.
#
# Requires: SSH access to root@68.183.130.3 (VPS) or `docker exec` on a
# host where regknots-postgres is running. Reads the source name from
# arg 1. Uses the same credentials the app uses.
#
# Examples:
#   scripts/rollback_source.sh uscg_bulletin
#   scripts/rollback_source.sh uscg_bulletin 48
#   scripts/rollback_source.sh nmc_policy

set -euo pipefail

SOURCE="${1:-}"
HOURS="${2:-24}"

if [[ -z "$SOURCE" ]]; then
    echo "usage: $0 <source> [hours]" >&2
    echo "       <source> matches regulations.source (e.g. uscg_bulletin)" >&2
    echo "       [hours]  rollback window for notification cleanup, default 24" >&2
    exit 1
fi

# Allow override for local testing; default target is the live VPS.
PGHOST="${RGK_PGHOST:-docker exec regknots-postgres}"
PSQL_CMD=(docker exec regknots-postgres psql -U regknots -d regknots)

cat <<EOF
Rolling back source: $SOURCE
Notification cleanup window: last $HOURS hour(s)

This will:
  1. DELETE all rows from regulations WHERE source='$SOURCE'
  2. DEACTIVATE regulation_update notifications for that source
     created within the last ${HOURS}h
  3. Run both in a single transaction (BEGIN..COMMIT)

Press Ctrl-C within 5s to abort.
EOF
sleep 5

"${PSQL_CMD[@]}" <<SQL
BEGIN;

-- Capture counts for the post-op summary.
\set ON_ERROR_STOP on
\qecho '=== Before ==='
SELECT source, COUNT(*) AS corpus_rows
FROM regulations
WHERE source = '${SOURCE}'
GROUP BY source;

SELECT COUNT(*) AS active_notifications
FROM notifications
WHERE notification_type = 'regulation_update'
  AND source = '${SOURCE}'
  AND is_active = true
  AND created_at > NOW() - INTERVAL '${HOURS} hours';

-- Do the work.
DELETE FROM regulations WHERE source = '${SOURCE}';

UPDATE notifications
   SET is_active = false
 WHERE notification_type = 'regulation_update'
   AND source = '${SOURCE}'
   AND is_active = true
   AND created_at > NOW() - INTERVAL '${HOURS} hours';

\qecho '=== After ==='
SELECT COUNT(*) AS remaining_corpus_rows
FROM regulations WHERE source = '${SOURCE}';

SELECT COUNT(*) AS remaining_active_notifications
FROM notifications
WHERE notification_type = 'regulation_update'
  AND source = '${SOURCE}'
  AND is_active = true;

COMMIT;

\qecho 'Rollback committed.'
SQL

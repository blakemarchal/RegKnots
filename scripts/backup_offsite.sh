#!/usr/bin/env bash
# scripts/backup_offsite.sh — sync local Postgres dumps offsite via rclone.
#
# 2026-07-19 — closes the "backups share a disk with the database" gap
# from the 2026-05-08 audit. A dead VPS disk currently loses the DB and
# every backup of it simultaneously.
#
# ⚠ REQUIRES ONE-TIME OPERATOR SETUP (≈5 min, needs account owner):
#   1. DigitalOcean console → Spaces → create bucket (suggest:
#      "regknots-backups", region SFO3/NYC3, NOT the droplet's region if
#      you want geo-separation) → generate Spaces access key + secret.
#   2. On the VPS:  apt-get install -y rclone   (or use the install script)
#   3. Write /root/.config/rclone/rclone.conf:
#        [offsite]
#        type = s3
#        provider = DigitalOcean
#        access_key_id = <SPACES_KEY>
#        secret_access_key = <SPACES_SECRET>
#        endpoint = sfo3.digitaloceanspaces.com
#      chmod 600 /root/.config/rclone/rclone.conf
#   4. sudo cp deploy/systemd/regknots-backup-offsite.{service,timer} /etc/systemd/system/
#      sudo systemctl daemon-reload && sudo systemctl enable --now regknots-backup-offsite.timer
#   5. Verify: sudo systemctl start regknots-backup-offsite.service && journalctl -u regknots-backup-offsite -n 20
#
# Until step 3 exists this script exits 5 with a loud message — safe to
# install the timer early; it fails visibly instead of pretending.
#
# What it does once configured:
#   1. rclone sync of the local backup dir → offsite bucket. `sync`
#      mirrors retention: local prunes (14d) propagate offsite, keeping
#      the bucket bounded (~11 GB at current 762MB/day × 14).
#   2. Verifies the newest local dump exists offsite AND size-matches.
#   3. Prints the offsite object count + total size for the journal.
#
# Env overrides:
#   BACKUP_DIR       default /var/backups/regknots
#   RCLONE_REMOTE    default offsite:regknots-backups/postgres

set -euo pipefail

readonly BACKUP_DIR="${BACKUP_DIR:-/var/backups/regknots}"
readonly RCLONE_REMOTE="${RCLONE_REMOTE:-offsite:regknots-backups/postgres}"

if ! command -v rclone >/dev/null 2>&1; then
    echo "ERROR: rclone not installed — run: apt-get install -y rclone" >&2
    exit 5
fi
if ! rclone listremotes 2>/dev/null | grep -q '^offsite:'; then
    echo "ERROR: rclone remote 'offsite' not configured. See header of this script for the 5-minute setup (needs DO Spaces keys — account owner action)." >&2
    exit 5
fi

echo "[$(date -u +%FT%TZ)] offsite sync ${BACKUP_DIR} → ${RCLONE_REMOTE}"
rclone sync "$BACKUP_DIR" "$RCLONE_REMOTE" \
    --include 'regknots-*.sql.gz' \
    --transfers 2 --checkers 4 \
    --s3-chunk-size 64M \
    --stats-one-line --stats 30s

# Verify newest local dump landed offsite with matching size.
newest_local="$(ls -t "$BACKUP_DIR"/regknots-*.sql.gz | head -1)"
newest_name="$(basename "$newest_local")"
local_size="$(stat -c '%s' "$newest_local")"
remote_size="$(rclone size "$RCLONE_REMOTE" --include "$newest_name" --json | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')"
if [[ "$remote_size" != "$local_size" ]]; then
    echo "ERROR: offsite verification failed for ${newest_name} (local=${local_size} remote=${remote_size:-missing})" >&2
    exit 6
fi
echo "[$(date -u +%FT%TZ)] verified ${newest_name} offsite (${local_size} bytes)"

rclone size "$RCLONE_REMOTE" | sed "s/^/[$(date -u +%FT%TZ)] offsite total: /"
echo "[$(date -u +%FT%TZ)] offsite sync complete"

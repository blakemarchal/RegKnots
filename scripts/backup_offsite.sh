#!/usr/bin/env bash
# scripts/backup_offsite.sh — copy the nightly backups offsite, encrypted.
#
# 2026-07-19 — closes the "backups share a disk with the database" gap
# from the 2026-05-08 audit. A dead VPS disk currently loses the DB and
# every backup of it simultaneously.
#
# 2026-10-16 (security review) — every file is encrypted with age to a
# public key before it leaves the box: the database dumps hold every
# account, and the uploads archive holds credentials and documents. Only
# the public key lives on the VPS; the private key stays with Blake. The
# script refuses to upload anything until the public key exists.
#
# ⚠ REQUIRES ONE-TIME OPERATOR SETUP (≈10 min, needs account owner):
#   1. DigitalOcean console → Spaces → create bucket (suggest:
#      "regknots-backups", region SFO3/NYC3, NOT the droplet's region if
#      you want geo-separation) → generate Spaces access key + secret.
#   2. On the VPS:  apt-get install -y rclone age
#   3. Write /root/.config/rclone/rclone.conf:
#        [offsite]
#        type = s3
#        provider = DigitalOcean
#        access_key_id = <SPACES_KEY>
#        secret_access_key = <SPACES_SECRET>
#        endpoint = sfo3.digitaloceanspaces.com
#      chmod 600 /root/.config/rclone/rclone.conf
#   4. On your laptop (not the VPS): install age (Windows: winget install
#      FiloSottile.age), run  age-keygen -o regknots-backup.key  and keep that
#      file in your password manager: it is the only way to read the offsite
#      copies. Put the "public key: age1..." line it prints into
#      /etc/regknots/backup-age.pub on the VPS (mkdir -p /etc/regknots first).
#   5. sudo cp deploy/systemd/regknots-backup-offsite.{service,timer} /etc/systemd/system/
#      sudo systemctl daemon-reload && sudo systemctl enable --now regknots-backup-offsite.timer
#   6. Verify: sudo systemctl start regknots-backup-offsite.service && journalctl -u regknots-backup-offsite -n 20
#
# Until steps 2–4 exist this script exits 5 with a loud message — safe to
# install the timer early; it fails visibly instead of pretending.
#
# What it does once configured:
#   1. Encrypts each local backup (regknots-*.sql.gz, regknots-uploads-*.tar.gz)
#      into ${BACKUP_DIR}/offsite/<name>.age, once per file; staged copies whose
#      source was pruned are removed, so retention carries over.
#   2. rclone sync of the staging dir → offsite bucket.
#   3. Verifies the newest staged dump exists offsite AND size-matches.
#   4. Prints the offsite object count + total size for the journal.
#
# Restore: age -d -i regknots-backup.key regknots-YYYYMMDD-HHMMSS.sql.gz.age > dump.sql.gz
# (then docs/runbooks/db-restore.md).
#
# Env overrides:
#   BACKUP_DIR       default /var/backups/regknots
#   RCLONE_REMOTE    default offsite:regknots-backups/postgres
#   AGE_RECIPIENTS   default /etc/regknots/backup-age.pub

set -euo pipefail

readonly BACKUP_DIR="${BACKUP_DIR:-/var/backups/regknots}"
readonly RCLONE_REMOTE="${RCLONE_REMOTE:-offsite:regknots-backups/postgres}"
readonly AGE_RECIPIENTS="${AGE_RECIPIENTS:-/etc/regknots/backup-age.pub}"
readonly STAGING="${BACKUP_DIR}/offsite"

if ! command -v rclone >/dev/null 2>&1; then
    echo "ERROR: rclone not installed — run: apt-get install -y rclone" >&2
    exit 5
fi
if ! rclone listremotes 2>/dev/null | grep -q '^offsite:'; then
    echo "ERROR: rclone remote 'offsite' not configured. See header of this script for the setup (needs DO Spaces keys — account owner action)." >&2
    exit 5
fi
if ! command -v age >/dev/null 2>&1; then
    echo "ERROR: age not installed — run: apt-get install -y age" >&2
    exit 5
fi
if [[ ! -s "$AGE_RECIPIENTS" ]] || ! grep -q '^age1' "$AGE_RECIPIENTS"; then
    echo "ERROR: no age public key at ${AGE_RECIPIENTS}; refusing to upload unencrypted backups. See step 4 in the header." >&2
    exit 5
fi

mkdir -p "$STAGING"
chmod 700 "$STAGING"

# 1. Encrypt what isn't staged yet; drop staged copies whose source is gone.
encrypted=0
shopt -s nullglob
for src in "$BACKUP_DIR"/regknots-*.sql.gz "$BACKUP_DIR"/regknots-uploads-*.tar.gz; do
    dest="${STAGING}/$(basename "$src").age"
    if [[ ! -s "$dest" ]]; then
        age -R "$AGE_RECIPIENTS" -o "${dest}.part" "$src"
        mv "${dest}.part" "$dest"
        chmod 600 "$dest"
        encrypted=$((encrypted + 1))
    fi
done
for staged in "$STAGING"/*.age; do
    [[ -e "${BACKUP_DIR}/$(basename "$staged" .age)" ]] || rm -f "$staged"
done
rm -f "$STAGING"/*.part
echo "[$(date -u +%FT%TZ)] encrypted ${encrypted} new backup file(s) for offsite"

# 2. Sync the encrypted copies.
echo "[$(date -u +%FT%TZ)] offsite sync ${STAGING} → ${RCLONE_REMOTE}"
rclone sync "$STAGING" "$RCLONE_REMOTE" \
    --include '*.age' \
    --transfers 2 --checkers 4 \
    --s3-chunk-size 64M \
    --stats-one-line --stats 30s

# 3. Verify the newest dump landed offsite with matching size.
newest_staged="$(ls -t "$STAGING"/regknots-*.sql.gz.age | head -1)"
newest_name="$(basename "$newest_staged")"
local_size="$(stat -c '%s' "$newest_staged")"
remote_size="$(rclone size "$RCLONE_REMOTE" --include "$newest_name" --json | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')"
if [[ "$remote_size" != "$local_size" ]]; then
    echo "ERROR: offsite verification failed for ${newest_name} (local=${local_size} remote=${remote_size:-missing})" >&2
    exit 6
fi
echo "[$(date -u +%FT%TZ)] verified ${newest_name} offsite (${local_size} bytes)"

rclone size "$RCLONE_REMOTE" | sed "s/^/[$(date -u +%FT%TZ)] offsite total: /"
echo "[$(date -u +%FT%TZ)] offsite sync complete"

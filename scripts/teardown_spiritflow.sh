#!/usr/bin/env bash
# scripts/teardown_spiritflow.sh — remove SpiritFlow from the shared
# VPS (spiritflow-prod-01) while preserving everything RegKnots.
#
# Run ONLY on the production VPS (root@68.183.130.3). Designed to be
# executed by Blake interactively — every destructive phase pauses for
# explicit confirmation before continuing. The recon Claude did before
# generating this script is documented at the top of each phase.
#
# Recovery estimate: ~5.1 GB across /opt/spiritflow (5 GB), /root
# leftovers (~110 MB), node_modules global package (~50 MB).
#
# Pre-condition: SSH'd to root@68.183.130.3 with this script available.
#
# Recommended invocation:
#   bash scripts/teardown_spiritflow.sh

set -u  # treat unset vars as errors; do NOT use `set -e` because we
        # want each phase to print its own success/failure cleanly.

# Colors (fall back to plain when not a TTY)
if [[ -t 1 ]]; then
    R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[34m'; X=$'\033[0m'
else
    R=''; G=''; Y=''; B=''; X=''
fi

pause_confirm() {
    local prompt="${1:-Continue?}"
    echo
    read -rp "${Y}>>> ${prompt} [yes/NO] ${X}" reply
    [[ "${reply,,}" == "yes" ]]
}

heading() {
    echo
    echo "${B}═══════════════════════════════════════════════════════════════${X}"
    echo "${B}  $1${X}"
    echo "${B}═══════════════════════════════════════════════════════════════${X}"
}

# ── Phase 0: Safety sanity ────────────────────────────────────────────
heading "Phase 0 — Safety sanity checks"

if [[ "$(hostname)" != "spiritflow-prod-01" ]]; then
    echo "${R}FATAL${X}: hostname is '$(hostname)' — expected 'spiritflow-prod-01'."
    echo "       Run this only on the production VPS."
    exit 1
fi
echo "  hostname OK: spiritflow-prod-01"

if [[ ! -d /opt/RegKnots ]]; then
    echo "${R}FATAL${X}: /opt/RegKnots not found. Aborting — wrong host?"
    exit 1
fi
echo "  /opt/RegKnots present (RegKnots intact)"

if ! systemctl is-active --quiet regknots-api; then
    echo "${Y}WARN${X}: regknots-api is not active. Pre-existing issue, not from this script."
fi

echo
echo "  Disk usage BEFORE teardown:"
df -h / 2>&1 | grep -E "^Filesystem|^/dev"

# ── Phase 1: Optional backup ───────────────────────────────────────────
heading "Phase 1 — Optional backup of /opt/spiritflow"

echo "  Recommend backing up /opt/spiritflow to ~/spiritflow-backup-$(date +%Y%m%d).tar.gz"
echo "  before deleting. The directory has 43 subdirs including many app.bak.*"
echo "  iterations from your March deploy session — possibly historical interest."
echo
echo "  Size: $(du -sh /opt/spiritflow/ 2>/dev/null | cut -f1)"
echo
if pause_confirm "Create tarball backup before delete?"; then
    BACKUP="/root/spiritflow-backup-$(date +%Y%m%d-%H%M%S).tar.gz"
    echo "  Creating ${BACKUP}…"
    tar -czf "${BACKUP}" -C /opt spiritflow
    echo "  ${G}Backup created${X}: ${BACKUP} ($(du -sh "${BACKUP}" | cut -f1))"
else
    echo "  Skipping backup. Proceeding without."
fi

# ── Phase 2: Stop services ─────────────────────────────────────────────
heading "Phase 2 — Stop and disable SpiritFlow systemd units"

echo "  Will stop + disable:"
echo "    - spiritflow-webhook.service (npm webhook server, port 8788)"
echo "    - openclaw-gateway.service   (depends on spiritflow-webhook)"
echo
echo "  Currently running processes (PIDs):"
ps auxf 2>&1 | grep -iE "(spiritflow|openclaw)" | grep -v grep | awk '{print "    pid="$2" "$11" "$12" "$13}' | head -10
echo
if ! pause_confirm "Stop + disable both services?"; then
    echo "  ${R}Aborted at Phase 2${X}"
    exit 0
fi

for unit in openclaw-gateway.service spiritflow-webhook.service; do
    echo "  Stopping ${unit}…"
    systemctl stop "${unit}" 2>&1 || echo "    ${Y}(stop returned non-zero; may already be stopped)${X}"
    systemctl disable "${unit}" 2>&1 || echo "    ${Y}(disable returned non-zero)${X}"
done

echo
echo "  Verifying services are inactive:"
for unit in openclaw-gateway.service spiritflow-webhook.service; do
    state=$(systemctl is-active "${unit}" 2>&1)
    echo "    ${unit}: ${state}"
done

# ── Phase 3: Remove systemd unit files ─────────────────────────────────
heading "Phase 3 — Remove systemd unit files"

echo "  Will remove:"
echo "    /etc/systemd/system/spiritflow-webhook.service"
echo "    /etc/systemd/system/openclaw-gateway.service"
echo
if ! pause_confirm "Remove unit files + daemon-reload?"; then
    echo "  ${R}Aborted at Phase 3${X}"
    exit 0
fi

rm -fv /etc/systemd/system/spiritflow-webhook.service
rm -fv /etc/systemd/system/openclaw-gateway.service
systemctl daemon-reload
systemctl reset-failed 2>&1 || true
echo "  ${G}Unit files removed${X}, daemon reloaded."

# ── Phase 4: Caddy config — remove spiritflow.church block ─────────────
heading "Phase 4 — Caddy config (remove spiritflow.church block, keep RegKnots)"

echo "  Will edit /etc/caddy/Caddyfile to remove the spiritflow.church"
echo "  reverse_proxy block. Backup copy will be created in /etc/caddy/"
echo "  before the edit."
echo
echo "  Current spiritflow block (4 lines):"
grep -A 2 "spiritflow.church" /etc/caddy/Caddyfile 2>&1 | sed 's/^/    /'
echo
if ! pause_confirm "Edit Caddyfile + reload caddy?"; then
    echo "  ${R}Aborted at Phase 4${X}"
    exit 0
fi

cp -v /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.bak.spiritflow-teardown-$(date +%Y%m%d_%H%M%S)"

# Remove the 4-line block:
#   spiritflow.church, www.spiritflow.church {
#       reverse_proxy 127.0.0.1:8788
#   }
#   <blank line>
# We anchor on the opening line + 3 lines after.
python3 <<'PYEOF'
import re
from pathlib import Path
p = Path("/etc/caddy/Caddyfile")
text = p.read_text()
# Remove the spiritflow.church block including the trailing blank line.
new = re.sub(
    r"\n*spiritflow\.church.*?\n\}\n",
    "\n",
    text,
    count=1,
    flags=re.DOTALL,
)
if new == text:
    print("  WARN: no spiritflow.church block matched; file unchanged.")
else:
    p.write_text(new)
    print("  spiritflow.church block removed from Caddyfile.")
PYEOF

if caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile 2>&1 | grep -E "(error|invalid)" -i; then
    echo "  ${R}FATAL${X}: Caddy validation failed after edit. Restoring backup."
    cp -v /etc/caddy/Caddyfile.bak.spiritflow-teardown-* /etc/caddy/Caddyfile | head -1
    exit 1
fi
systemctl reload caddy
echo "  ${G}Caddy reloaded${X}. regknots.com should remain unaffected — verify in browser."

# ── Phase 5: File deletion ─────────────────────────────────────────────
heading "Phase 5 — Delete SpiritFlow files + directories"

echo "  Will delete:"
echo "    /opt/spiritflow/                              ($(du -sh /opt/spiritflow/ 2>/dev/null | cut -f1))"
echo "    /etc/spiritflow/                              ($(du -sh /etc/spiritflow/ 2>/dev/null | cut -f1))"
echo "    /home/spiritflow/                             ($(du -sh /home/spiritflow/ 2>/dev/null | cut -f1))"
echo "    /root/faithflow-deploy.tar.gz                 (23 MB)"
echo "    /root/faithflow.db                            (0 B)"
echo "    /root/DATABASE.md, /root/auth-profiles.json, /root/.env.example"
echo "    /root/package.json, /root/package-lock.json"
echo "    /root/node_modules/                           ($(du -sh /root/node_modules/ 2>/dev/null | cut -f1))"
echo "    /root/public/                                 ($(du -sh /root/public/ 2>/dev/null | cut -f1))"
echo "    /root/.tmp/                                   ($(du -sh /root/.tmp/ 2>/dev/null | cut -f1))"
echo "    /root/.git/                                   ($(du -sh /root/.git/ 2>/dev/null | cut -f1)) — SpiritFlow workspace git repo, NOT your ~/.gitconfig"
echo "    /root/.gitignore                              (SpiritFlow workspace gitignore)"
echo "  ${G}EXPLICITLY KEEPING:${X}"
echo "    /root/.gitconfig    (your personal git user.email/name)"
echo "    /root/.ssh, /root/.bashrc, /root/.zshrc, /root/.profile  (your shell + auth config)"
echo "    /root/.bash_history, /root/.cache, /root/.config, /root/.local, /root/.npm"
echo "    /root/C:                                      (Windows-style path artifact — leaving for you to triage)"
echo
if ! pause_confirm "Proceed with file deletion?"; then
    echo "  ${R}Aborted at Phase 5${X}"
    exit 0
fi

# /opt + /etc + /home
rm -rfv /opt/spiritflow/
rm -rfv /etc/spiritflow/
rm -rfv /home/spiritflow/

# /root SpiritFlow / faithflow artifacts
rm -fv  /root/faithflow-deploy.tar.gz
rm -fv  /root/faithflow.db
rm -fv  /root/DATABASE.md
rm -fv  /root/auth-profiles.json
rm -fv  /root/.env.example
rm -fv  /root/package.json
rm -fv  /root/package-lock.json
rm -fv  /root/.gitignore
rm -rfv /root/node_modules/
rm -rfv /root/public/
rm -rfv /root/.tmp/
rm -rfv /root/.git/

echo "  ${G}Files removed.${X}"

# ── Phase 6: Cron line + user account ──────────────────────────────────
heading "Phase 6 — Cron line + user account"

echo "  Current root crontab (filtering SpiritFlow-related):"
crontab -l 2>&1 | grep -E "(spiritflow|faithflow)" | sed 's/^/    /'
echo
echo "  Will remove the faithflow.db backup line from root's crontab."
echo "  Will delete the 'spiritflow' user account (UID 1000)."
echo
if ! pause_confirm "Remove cron line + delete spiritflow user?"; then
    echo "  ${R}Aborted at Phase 6${X}"
    exit 0
fi

# Filter the spiritflow line out of crontab
crontab -l 2>/dev/null | grep -v -E "(spiritflow|faithflow)" | crontab -
echo "  Crontab cleaned. Remaining lines:"
crontab -l 2>&1 | sed 's/^/    /'

# Delete the user (home dir already deleted in Phase 5)
if id spiritflow &>/dev/null; then
    userdel spiritflow 2>&1 && echo "  ${G}spiritflow user removed${X}"
else
    echo "  spiritflow user already absent."
fi

# ── Phase 7: openclaw binary + npm global package ──────────────────────
heading "Phase 7 — openclaw binary + global npm package"

echo "  /usr/bin/openclaw is a symlink to /lib/node_modules/openclaw/openclaw.mjs."
echo "  Will uninstall the global openclaw npm package, which removes both."
echo
if ! pause_confirm "Uninstall global openclaw npm package?"; then
    echo "  ${Y}Skipping. You can remove manually later with:${X}"
    echo "    npm uninstall -g openclaw"
else
    npm uninstall -g openclaw 2>&1 || echo "  ${Y}(npm uninstall returned non-zero; try: rm -rfv /lib/node_modules/openclaw/ /usr/bin/openclaw)${X}"
fi

# ── Phase 8: Verification ──────────────────────────────────────────────
heading "Phase 8 — Verification"

echo
echo "  Disk usage AFTER teardown:"
df -h / 2>&1 | grep -E "^Filesystem|^/dev"
echo
echo "  Running processes — should have NO spiritflow / openclaw entries:"
remaining=$(ps auxf 2>&1 | grep -iE "(spiritflow|openclaw|faithflow)" | grep -v grep)
if [[ -z "${remaining}" ]]; then
    echo "    ${G}clean.${X}"
else
    echo "${remaining}" | sed 's/^/    /'
fi
echo
echo "  Listening on 8788 (was: spiritflow webhook):"
ss -tlnp 2>&1 | grep ":8788 " || echo "    ${G}nothing listening.${X}"
echo
echo "  RegKnots services — all should be active:"
for svc in regknots-api regknots-web regknots-worker; do
    state=$(systemctl is-active "${svc}" 2>&1)
    echo "    ${svc}: ${state}"
done
echo
echo "  RegKnots docker containers:"
docker ps --filter name=regknots --format "    {{.Names}}: {{.Status}}"
echo
echo "  Caddy config remaining domains:"
grep -E "^[a-z].*{" /etc/caddy/Caddyfile 2>&1 | sed 's/^/    /'
echo
echo "  ${G}Teardown complete.${X}"
echo "  Final smoke check: hit https://regknots.com/api/health and the chat UI"
echo "  from a browser to confirm no regression from this teardown."

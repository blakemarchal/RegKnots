#!/usr/bin/env bash
# scripts/run_ingest.sh — run an ad-hoc ingest job inside a memory-capped
# transient systemd unit so it can't take the box.
#
# Background: the audit traced 12 of the 13 OOM events / 14 days to
# `task=python3` in interactive SSH sessions — i.e. someone running
# `uv run python -m ingest.cli ...` in a shell. The default behavior of
# such a job is "no memory cap, can grow until kernel OOM kills something
# random." If the random thing happens to be regknots-api or the
# SpiritFlow co-tenant, the user-visible blast radius is huge.
#
# This wrapper runs the same command inside `systemd-run` with:
#   - its own cgroup (regknots-ingest.slice)
#   - MemoryHigh=1G (soft throttle)
#   - MemoryMax=1.5G (hard kill at 1.5 GB — way more than any sane ingest needs)
#   - logs streaming to journald (visible in `systemctl status` and
#     `journalctl -u <transient-unit-name>`)
#
# Usage:
#   scripts/run_ingest.sh [args passed to `uv run python -m ingest.cli`]
#
# Examples:
#   scripts/run_ingest.sh --source nvic --dry-run
#   scripts/run_ingest.sh --source uscg_bulletin --since 2026-04-01
#   scripts/run_ingest.sh --refresh-stale
#
# Run from the repo root or from anywhere; it cd's to /opt/RegKnots.
#
# After the job finishes, view the log:
#   journalctl -u regknots-ingest-<timestamp>.service --no-pager

set -euo pipefail

readonly REPO="${REGKNOTS_REPO:-/opt/RegKnots}"
readonly UNIT="regknots-ingest-$(date -u +%Y%m%d-%H%M%S)"

# Refuse to run if not inside the repo dir.
if [[ ! -f "${REPO}/packages/ingest/ingest/cli.py" ]]; then
    echo "ERROR: ${REPO}/packages/ingest/ingest/cli.py not found" >&2
    echo "       set REGKNOTS_REPO env var if your checkout is elsewhere" >&2
    exit 1
fi

# Run the ingest command inside a transient systemd unit. systemd-run
# echoes the unit name to stderr, then waits for the command to finish
# (because of --wait) and forwards the exit code.
#
# Why `--collect`: we want the unit to be removed from systemd's
# bookkeeping after it exits so we don't accumulate hundreds of stale
# transient units. Logs persist in journald.
#
# Why `--pty`: lets the ingest's interactive progress bar render in the
# terminal even though it's now running in a transient unit context.
exec systemd-run \
    --unit="${UNIT}" \
    --slice=regknots-ingest.slice \
    --wait \
    --pty \
    --collect \
    --working-directory="${REPO}" \
    --property=MemoryHigh=1G \
    --property=MemoryMax=1.5G \
    --property=CPUQuota=150% \
    /root/.local/bin/uv run --project "${REPO}/apps/api" python -m ingest.cli "$@"

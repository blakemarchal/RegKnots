#!/usr/bin/env bash
# Sprint D6.43 — periodic corpus refresh.
#
# Designed to be called from a systemd timer (see scripts/regknots-refresh.timer).
# Runs the ingest CLI in --update mode for sources that change frequently.
# Uses --update (not --fresh) so unchanged chunks are skipped — only modified
# content gets re-embedded. Cheap on the OpenAI bill.
#
# Schedule recommendation:
#   weekly  — CFR 33/46/49, USCG bulletins, NVIC
#   monthly — flag-state regulators, MPA SG, BMA, HK MD, MCA, AMSA
#   quarterly — IMO supplements, MOU PSC reports, IACS UR
#
# Logs to /var/log/regknots-refresh.log; failures are emitted to stderr
# (which systemd captures into journal). Returns non-zero if any source
# errors so the timer can surface failures via OnFailure= units.
#
# Usage:
#   ./corpus_refresh.sh weekly       # Just weekly tier
#   ./corpus_refresh.sh monthly      # Just monthly tier (also runs weekly)
#   ./corpus_refresh.sh quarterly    # Full pass (weekly + monthly + quarterly)
#   ./corpus_refresh.sh all          # Same as quarterly

set -euo pipefail

INGEST_ROOT="${INGEST_ROOT:-/opt/RegKnots/packages/ingest}"
UV_BIN="${UV_BIN:-/root/.local/bin/uv}"
LOG="${LOG:-/var/log/regknots-refresh.log}"
TIER="${1:-weekly}"

log() {
  echo "[$(date -Is)] $*" | tee -a "$LOG"
}

run_source() {
  local src="$1"
  log "REFRESH: $src"
  if cd "$INGEST_ROOT" && "$UV_BIN" run python -m ingest.cli \
        --source "$src" --update --no-notify --no-enrich >>"$LOG" 2>&1
  then
    log "  → ok: $src"
    return 0
  else
    log "  → FAIL: $src (exit $?)"
    return 1
  fi
}

# ── Weekly tier — fast-changing federal sources ──────────────────────────
WEEKLY=(
  cfr_33
  cfr_46
  cfr_49
  uscg_bulletin
  nvic
)

# ── Monthly tier — flag-state regulators publishing notices regularly ────
MONTHLY=(
  mca_mgn
  mca_msn
  amsa_mo
  mardep_msin
  nma_rsv
  liscr_mn
  iri_mn
  bma_mn
  mpa_sc
)

# ── Quarterly tier — IMO supplements + slow-moving sources ───────────────
QUARTERLY=(
  marpol_supplement
  marpol_amend
  stcw_supplement
  stcw_amend
  ism_supplement
  solas_supplement
  imdg_supplement
  imo_polar
  imo_igf
  imo_bwm
  iacs_ur
  mou_psc
  uscg_msm
  nmc_policy
  nmc_checklist
)

failed=0
case "$TIER" in
  weekly)
    sources=("${WEEKLY[@]}")
    ;;
  monthly)
    sources=("${WEEKLY[@]}" "${MONTHLY[@]}")
    ;;
  quarterly|all)
    sources=("${WEEKLY[@]}" "${MONTHLY[@]}" "${QUARTERLY[@]}")
    ;;
  *)
    echo "Unknown tier: $TIER (expected weekly|monthly|quarterly|all)" >&2
    exit 2
    ;;
esac

log "=== refresh start: tier=$TIER, ${#sources[@]} sources ==="
for src in "${sources[@]}"; do
  run_source "$src" || failed=$((failed + 1))
done
log "=== refresh end: $failed failures ==="

exit $failed

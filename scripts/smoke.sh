#!/usr/bin/env bash
# scripts/smoke.sh — content-asserting smoke probes against production.
#
# CRITICAL: don't trust HTTP 200 alone. Next.js client-rendered pages
# return 200 with a SSR shell containing only a loading spinner — the
# real content is in a JS chunk fetched after hydration. If the chunk
# isn't refreshed (build didn't roll), the page can return 200 *while
# missing the new content*. That's the silent-failure mode that hid
# Phase A3-A5 deploys from us.
#
# Each PROBE asserts:
#   1. the page returns 200
#   2. the SSR HTML references a route-specific JS bundle
#      (e.g. app/education/page-<hash>.js)
#   3. the JS chunk itself contains a "canary string" — a distinctive
#      substring known to exist in the latest source code for that
#      route. If a previous build is being served, the canary will
#      not be present in the chunk content.
#
# Usage:
#   scripts/smoke.sh                  # full smoke
#   scripts/smoke.sh /education       # one route
#   BASE_URL=http://localhost:3000 scripts/smoke.sh   # against dev

set -euo pipefail

readonly BASE_URL="${BASE_URL:-https://regknots.com}"
readonly CURL_OPTS=(-s --ssl-no-revoke -L --max-time 20)

# Probe table:  ROUTE | BUNDLE_GLOB | CANARY_REGEX
# Bundle glob is the path used to locate the page-specific JS chunk in
# the SSR HTML. Canary regex is grep -E pattern that MUST appear in
# the chunk content. Pick a string that's distinctive to the latest
# version of that page so a stale build is detected.
PROBES=(
  "/education|app/education/page-|Pass your USCG"
  "/study|app/study/page-|Generate quiz|Generate guide|Quizzes"
  "/account|app/account/page-|study_tools_enabled|Quizzes"
  "/landing|app/landing/page-|RegKnot"
  "/login|app/login/page-|Sign In|password"
)

# Allow a single-route override.
if [[ "${1:-}" != "" ]]; then
    PROBES=("${1}|app${1}/page-|.")
fi

fail=0
echo "BASE_URL=$BASE_URL"
echo ""

for probe in "${PROBES[@]}"; do
    route="${probe%%|*}"
    rest="${probe#*|}"
    bundle_pat="${rest%%|*}"
    canary="${rest#*|}"

    printf "  %-15s " "$route"

    # 1. status
    code=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' "$BASE_URL$route" || true)
    if [[ "$code" != "200" ]]; then
        echo "FAIL: HTTP $code"
        fail=1
        continue
    fi

    # 2. SSR HTML references the route-specific JS bundle
    html=$(curl "${CURL_OPTS[@]}" "$BASE_URL$route")
    chunk=$(echo "$html" | grep -oE "${bundle_pat}[a-f0-9]+\.js" | head -1)
    if [[ -z "$chunk" ]]; then
        echo "FAIL: route bundle not in HTML (pattern: ${bundle_pat}<hash>.js)"
        fail=1
        continue
    fi

    # 3. JS chunk contains canary string
    chunk_body=$(curl "${CURL_OPTS[@]}" "$BASE_URL/_next/static/chunks/${chunk}")
    if ! echo "$chunk_body" | grep -qE "$canary"; then
        echo "FAIL: chunk missing canary (expected /${canary}/)"
        fail=1
        continue
    fi

    echo "ok ($chunk)"
done

# API health probes — different shape: 200 from /api/health is fine
# because FastAPI exposes the JSON directly; no client hydration step.
echo ""
echo "  /api/health     "
api_health=$(curl "${CURL_OPTS[@]}" -o /dev/null -w '%{http_code}' "$BASE_URL/api/health")
echo "                  $api_health"
if [[ "$api_health" != "200" ]]; then
    fail=1
fi

if [[ "$fail" -eq 0 ]]; then
    echo ""
    echo "smoke OK"
    exit 0
else
    echo ""
    echo "smoke FAILED"
    exit 3
fi

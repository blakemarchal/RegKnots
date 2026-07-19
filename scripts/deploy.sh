#!/usr/bin/env bash
# scripts/deploy.sh — one-shot deploy of origin/main to the VPS.
#
# Use case: you've merged a PR / pushed to main and want production at
# the new HEAD. There is no GitHub webhook for RegKnots; this script
# is the automation. Run it from your laptop after the push lands.
#
# Sequence:
#   1. ssh into the VPS as root
#   2. git fetch && git reset --hard origin/main  (NEVER edit in place)
#   3. apps/api: alembic upgrade head             (production lifespan
#      handler does NOT run migrations — only dev does)
#   4. apps/web: pnpm install --frozen-lockfile && pnpm build
#   5. systemctl restart regknots-api regknots-web regknots-worker
#   6. content-asserting smoke probes against the live URL — fail loud
#      if a route is 404 OR if the JS chunk doesn't contain a known
#      string from the new code (which catches "/study returned 200
#      but it's an old build" — the failure mode that bit us through
#      Phase A3-A5)
#
# Usage:
#   scripts/deploy.sh                              # deploy origin/main
#   scripts/deploy.sh --skip-build                 # api-only restart (rare)
#   scripts/deploy.sh --skip-smoke                 # don't wait on probes
#
# Exit codes:
#   0  — deploy + smoke passed
#   1  — pre-flight check failed (uncommitted local work, stale main)
#   2  — VPS step failed (build error, migration error, restart failed)
#   3  — smoke test failed (route missing or content not in bundle)

set -euo pipefail

readonly VPS="root@68.183.130.3"
readonly REPO="/opt/RegKnots"
readonly BASE_URL="https://regknots.com"

SKIP_BUILD=0
SKIP_SMOKE=0
for arg in "$@"; do
    case "$arg" in
        --skip-build) SKIP_BUILD=1 ;;
        --skip-smoke) SKIP_SMOKE=1 ;;
        -h|--help)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 1 ;;
    esac
done

# ── Pre-flight (local) ────────────────────────────────────────────────
echo "─── Pre-flight ───"
git fetch origin main --quiet
local_main_sha=$(git rev-parse origin/main)
echo "origin/main:   $local_main_sha"
echo "deploying to:  $VPS:$REPO"

# ── VPS: pull + (optionally) build + restart ──────────────────────────
echo ""
echo "─── VPS: pull + build + restart ───"
ssh "$VPS" SKIP_BUILD="$SKIP_BUILD" REPO="$REPO" 'bash -se' <<'REMOTE'
set -euo pipefail
cd "$REPO"

echo "[git] fetch + reset --hard origin/main"
git fetch origin main --quiet
git reset --hard origin/main >/dev/null
git log -1 --oneline

echo ""
echo "[alembic] upgrade head"
cd apps/api
/root/.local/bin/uv run alembic upgrade head 2>&1 | grep -E "^(INFO|ERROR)" | tail -5
cd ../..

if [[ "$SKIP_BUILD" != "1" ]]; then
    echo ""
    echo "[pnpm] install --frozen-lockfile"
    cd apps/web
    pnpm install --frozen-lockfile 2>&1 | tail -3
    echo ""
    echo "[pnpm] build (production)"
    # D6.97 Phase 2 — export NEXT_PUBLIC_* vars from the monorepo root
    # .env so Next.js inlines them into the build. Without this only
    # the inline NEXT_PUBLIC_API_URL below was visible to pnpm build —
    # NEXT_PUBLIC_SENTRY_DSN and NEXT_PUBLIC_CHAT_IMAGE_UPLOAD_ENABLED
    # silently behaved as if unset. We pick only NEXT_PUBLIC_* lines so
    # server-only secrets (Stripe / Anthropic / JWT keys) stay server-
    # side and never accidentally land in client JS.
    while IFS= read -r line; do
        if [[ "$line" =~ ^NEXT_PUBLIC_[A-Z0-9_]+= ]]; then
            export "$line"
        fi
    done < "$REPO/.env"
    NEXT_PUBLIC_API_URL=https://regknots.com/api pnpm build 2>&1 | tail -5
    cd ../..
fi

echo ""
echo "[systemd] restart api / web / worker"
systemctl restart regknots-api regknots-web regknots-worker

# 2026-07-19 — `systemctl is-active` only proves the process forked;
# regknots-web is Type=simple, so systemd marks it active the instant
# `pnpm start` launches, before Next.js finishes loading its build
# manifest into memory. Caught live: a request landing in that gap got
# served with no CSS (stale/incomplete manifest), self-healed a few
# seconds later on its own. Poll the app's OWN HTTP port for a real,
# content-bearing response instead of trusting systemd's process state.
for u in regknots-api regknots-web regknots-worker; do
    state=$(systemctl is-active "$u")
    printf "  %-20s %s\n" "$u" "$state"
    if [[ "$state" != "active" ]]; then
        echo "ERROR: $u is not active"
        exit 2
    fi
done

echo ""
echo "[readiness] waiting for regknots-web to serve a real build (CSS present)..."
web_ready=0
for i in $(seq 1 20); do
    html=$(curl -s --max-time 5 http://localhost:3000/login || true)
    if echo "$html" | grep -q '/_next/static/css/'; then
        echo "  ready after ${i}x1.5s"
        web_ready=1
        break
    fi
    sleep 1.5
done
if [[ "$web_ready" != "1" ]]; then
    echo "ERROR: regknots-web never served CSS-bearing HTML within 30s"
    exit 2
fi

echo "[readiness] waiting for regknots-api /health..."
api_ready=0
for i in $(seq 1 20); do
    code=$(curl -s --max-time 5 -o /dev/null -w '%{http_code}' http://localhost:8000/health || true)
    if [[ "$code" == "200" ]]; then
        echo "  ready after ${i}x1.5s"
        api_ready=1
        break
    fi
    sleep 1.5
done
if [[ "$api_ready" != "1" ]]; then
    echo "ERROR: regknots-api /health never returned 200 within 30s"
    exit 2
fi
REMOTE

# ── Smoke probes (run from the laptop, hits the public URL) ───────────
if [[ "$SKIP_SMOKE" == "1" ]]; then
    echo ""
    echo "deploy complete (smoke skipped)"
    exit 0
fi

echo ""
echo "─── Smoke ───"
exec scripts/smoke.sh

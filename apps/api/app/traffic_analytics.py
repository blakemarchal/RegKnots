"""Caddy access-log analytics.

Sprint D6.7 — free traffic analytics from the JSON access log Caddy
already writes (Sprint D6.6). Zero third-party services, zero MaxMind
GeoIP, zero client-side tracking pixels. Pure server-side aggregation.

Inputs: `/var/log/caddy/regknots-access.log` plus rotated siblings
(`*.log.1`, `*.log.2`, ...). Each line is a single JSON record produced
by Caddy's `format json` directive (see infra/caddy notes in
docs/scaling-roadmap.md). The fields we read are stable across Caddy
versions:

  ts                  unix epoch (float)
  status              HTTP status code (int)
  duration            response duration (float, seconds)
  size                response bytes (int)
  request.method      HTTP verb
  request.uri         path + query string
  request.host        Host header
  request.remote_ip   client IP (already proxied if any upstream)
  request.headers     dict of header arrays — User-Agent, Referer
                      (note: Caddy capitalises "Referer", not "Referrer")

Output: `TrafficSummary` covering the requested window. We bucket
requests by:
  - top_pages           — top human-visited HTML routes
  - top_api             — top human-hit API routes
  - top_referrers       — referer hostnames
  - utm_sources         — utm_source query param values
  - status_codes        — distribution
  - by_day              — daily human/bot/total counters
  - totals              — overall counters

Bots are classified by user-agent regex (no third-party DB). The bot
filter is on by default for human-facing dimensions so SentryUptimeBot
doesn't drown out the 1-4 real visitors per day. Raw bot traffic is
still surfaced separately so the operator can sanity-check.

Cache: in-process LRU keyed by (window_start, window_end). 5-minute
TTL. Reading 100MiB of log is sub-second and we can pay it on every
admin page-view, but the cache means rapid F5 doesn't hammer the disk.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# 5-minute in-process cache keyed by (log_dir, since_iso, until_iso).
# Sufficient for an admin dashboard with single-digit concurrent viewers.
_CACHE_TTL_SECONDS = 300
_cache: dict[tuple[str, str, str], tuple[float, "TrafficSummary"]] = {}
_cache_lock = asyncio.Lock()

# User agents we treat as automated. Conservative enough that real
# browsers (with "Mozilla/5.0 ... Safari/...") don't match. SentryUptimeBot
# is the dominant bot we'll see; the others guard against future
# crawlers without GeoIP-style data feeds.
_BOT_UA_RE = re.compile(
    r"(?:bot|crawler|spider|monitor|sentry|uptime|googlebot|bingbot|"
    r"baiduspider|yandex|duckduckbot|preview|axios/|curl/|python-requests|"
    r"wget/|httpx/|go-http-client|node-fetch|headlesschrome)",
    re.IGNORECASE,
)

# UUID-shaped path segments we collapse to ":id" so the top-pages chart
# doesn't fragment across thousands of distinct conversation IDs.
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
# Numeric-only segments (rare in our routes but cheap to handle) and any
# segment that's already templated.
_NUMERIC_RE = re.compile(r"^\d+$")

# Static-asset prefixes we don't count as "page visits" (they're noise
# from the same visit and bloat the top-N).
_STATIC_PREFIXES = (
    "/_next/", "/favicon", "/assets/", "/static/", "/icons/",
    "/manifest", "/robots.txt", "/sitemap", "/.well-known/",
    "/icon-",  # PWA icon variants (icon-192.png, icon-512.png, etc.)
    # PWA service-worker artifacts — show up on every page load and
    # would otherwise dominate the top-pages chart.
    "/sw.js", "/workbox-",
)


@dataclass
class TrafficSummary:
    since: str
    until: str
    log_files_scanned: list[str]
    total_requests: int = 0
    bot_requests: int = 0
    human_requests: int = 0
    unique_human_ips: int = 0
    top_pages: list[dict[str, Any]] = field(default_factory=list)
    top_api: list[dict[str, Any]] = field(default_factory=list)
    top_referrers: list[dict[str, Any]] = field(default_factory=list)
    utm_sources: list[dict[str, Any]] = field(default_factory=list)
    utm_campaigns: list[dict[str, Any]] = field(default_factory=list)
    status_codes: list[dict[str, Any]] = field(default_factory=list)
    by_day: list[dict[str, Any]] = field(default_factory=list)
    slow_requests: list[dict[str, Any]] = field(default_factory=list)


def _normalize_path(uri: str) -> tuple[str, dict[str, str]]:
    """Strip query string, collapse UUID/numeric path segments to :id.

    Returns (canonical_path, query_dict). Query values are first-only
    (parse_qs returns lists; we flatten so callers don't have to).
    """
    parsed = urlparse(uri)
    segments = parsed.path.split("/")
    normalized = []
    for seg in segments:
        if _UUID_RE.fullmatch(seg):
            normalized.append(":id")
        elif _NUMERIC_RE.fullmatch(seg) and len(seg) > 4:
            # 4-digit and shorter likely real (year, port). Longer numeric
            # is almost always an ID.
            normalized.append(":id")
        else:
            normalized.append(seg)
    canonical = "/".join(normalized) or "/"
    qs_raw = parse_qs(parsed.query, keep_blank_values=False)
    qs = {k: v[0] for k, v in qs_raw.items() if v}
    return canonical, qs


def _is_static(path: str) -> bool:
    return any(path.startswith(p) for p in _STATIC_PREFIXES)


def _is_bot(user_agent: str) -> bool:
    if not user_agent:
        # Empty UA is suspicious but not always a bot (some monitors).
        # Treating empty as bot reduces false-human inflation.
        return True
    return bool(_BOT_UA_RE.search(user_agent))


def _referrer_host(referrer: str | None, *, exclude: str = "regknots.com") -> str | None:
    if not referrer:
        return None
    try:
        host = urlparse(referrer).netloc.lower()
    except Exception:
        return None
    if not host:
        return None
    # Strip leading "www."
    if host.startswith("www."):
        host = host[4:]
    # Same-site referrals aren't interesting for attribution
    if host == exclude or host.endswith("." + exclude):
        return None
    return host


def _list_log_files(log_dir: Path) -> list[Path]:
    """Return regknots-access.log and rotated siblings, newest first.

    Caddy rolls files as `<base>.log` → `<base>-<timestamp>.log` (it does
    NOT use a `.log.N` suffix in this version). We just match anything
    with `regknots-access` in the name and a `.log` extension.
    """
    if not log_dir.is_dir():
        return []
    candidates = []
    for path in log_dir.iterdir():
        name = path.name
        if "regknots-access" in name and name.endswith(".log"):
            candidates.append(path)
        # Also accept `.log.gz` if compression gets enabled later
        elif "regknots-access" in name and name.endswith(".log.gz"):
            candidates.append(path)
    # Newest first by mtime
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates


def _iter_log_lines(path: Path):
    """Yield raw JSON-decoded log records, skipping malformed lines.

    Handles plain `.log` and gzipped `.log.gz` transparently. Logs
    decode failures are swallowed silently — the caller doesn't gain
    anything by surfacing them, and a corrupted line shouldn't tank
    the whole rollup.
    """
    if path.suffix == ".gz":
        import gzip
        opener = lambda: gzip.open(path, "rt", encoding="utf-8", errors="replace")
    else:
        opener = lambda: open(path, "r", encoding="utf-8", errors="replace")
    try:
        with opener() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    except OSError as e:
        logger.warning("traffic_analytics: failed reading %s: %s", path, e)


def _parse_logs_sync(
    log_dir: Path,
    since_utc: datetime,
    until_utc: datetime,
) -> TrafficSummary:
    """Synchronous parser. Wrapped in a thread executor by the async path."""
    files = _list_log_files(log_dir)
    summary = TrafficSummary(
        since=since_utc.isoformat(),
        until=until_utc.isoformat(),
        log_files_scanned=[p.name for p in files],
    )
    if not files:
        return summary

    since_ts = since_utc.timestamp()
    until_ts = until_utc.timestamp()

    page_counter: Counter[str] = Counter()
    page_unique: dict[str, set[str]] = defaultdict(set)
    api_counter: Counter[str] = Counter()
    api_unique: dict[str, set[str]] = defaultdict(set)
    referrer_counter: Counter[str] = Counter()
    referrer_unique: dict[str, set[str]] = defaultdict(set)
    utm_source_counter: Counter[str] = Counter()
    utm_source_unique: dict[str, set[str]] = defaultdict(set)
    utm_campaign_counter: Counter[str] = Counter()
    status_counter: Counter[int] = Counter()
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"human": 0, "bot": 0})
    slow_requests: list[dict[str, Any]] = []
    human_ips: set[str] = set()

    for path in files:
        for rec in _iter_log_lines(path):
            ts = rec.get("ts")
            if ts is None or not isinstance(ts, (int, float)):
                continue
            # Caddy rotates by size, so older files may be entirely outside
            # the window; we still scan them (cheap) but skip records
            # individually to keep counters accurate.
            if ts < since_ts or ts > until_ts:
                continue

            req = rec.get("request") or {}
            headers = req.get("headers") or {}
            ua_list = headers.get("User-Agent") or []
            ua = ua_list[0] if ua_list else ""
            referer_list = headers.get("Referer") or []
            referer = referer_list[0] if referer_list else ""

            method = (req.get("method") or "").upper()
            uri = req.get("uri") or "/"
            ip = req.get("remote_ip") or req.get("client_ip") or ""
            status = rec.get("status") or 0
            duration = rec.get("duration") or 0.0
            day = datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()

            summary.total_requests += 1
            status_counter[int(status)] += 1

            is_bot = _is_bot(ua)
            if is_bot:
                summary.bot_requests += 1
                by_day[day]["bot"] += 1
                # Skip dimensions for bots — they'd swamp the human signal
                continue

            summary.human_requests += 1
            by_day[day]["human"] += 1
            if ip:
                human_ips.add(ip)

            # Slow human requests worth surfacing (>2s, successful only —
            # 503/timeout already shows up in status distribution)
            if duration > 2.0 and 200 <= status < 400:
                slow_requests.append({
                    "ts": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
                    "uri": uri[:120],
                    "duration_ms": int(duration * 1000),
                    "status": int(status),
                })

            # Path bucketing — only count GET requests for the page-view
            # rollup; POST/PUT noise (form submits, API calls) goes in api.
            canonical, qs = _normalize_path(uri)
            if _is_static(canonical):
                continue

            # Successful-only buckets — 404s are mostly scanner noise
            # (`/.env`, `/wp-admin/install.php`, …) and would dominate the
            # top-N otherwise. The status_codes histogram still surfaces
            # the raw distribution so the operator can see scan volume.
            ok_status = 200 <= int(status) < 400

            if canonical.startswith("/api/"):
                # /api/admin/* and any /api/<feature>/admin/* (e.g.
                # /api/survey/admin/responses) is the operator's own
                # dashboard polling itself — counting it conflates "real
                # user API traffic" with "Blake's open admin tab."
                # Excluded by design.
                is_admin_route = (
                    canonical.startswith("/api/admin/")
                    or "/admin/" in canonical
                )
                if (
                    method in ("GET", "POST")
                    and ok_status
                    and not is_admin_route
                ):
                    api_counter[f"{method} {canonical}"] += 1
                    if ip:
                        api_unique[f"{method} {canonical}"].add(ip)
            else:
                if method == "GET" and ok_status:
                    page_counter[canonical] += 1
                    if ip:
                        page_unique[canonical].add(ip)

            # UTM tracking — only attribute on landing-page hits (HTML GET)
            # so each visit counts once even if downstream pages re-emit
            # the param.
            if method == "GET" and not canonical.startswith("/api/"):
                utm_source = qs.get("utm_source")
                if utm_source:
                    utm_source_counter[utm_source] += 1
                    if ip:
                        utm_source_unique[utm_source].add(ip)
                utm_campaign = qs.get("utm_campaign")
                if utm_campaign:
                    utm_campaign_counter[utm_campaign] += 1

            # Referrer attribution (external only)
            host = _referrer_host(referer)
            if host:
                referrer_counter[host] += 1
                if ip:
                    referrer_unique[host].add(ip)

    summary.unique_human_ips = len(human_ips)
    summary.top_pages = [
        {"path": p, "count": c, "unique_ips": len(page_unique[p])}
        for p, c in page_counter.most_common(20)
    ]
    summary.top_api = [
        {"path": p, "count": c, "unique_ips": len(api_unique[p])}
        for p, c in api_counter.most_common(15)
    ]
    summary.top_referrers = [
        {"host": h, "count": c, "unique_ips": len(referrer_unique[h])}
        for h, c in referrer_counter.most_common(15)
    ]
    summary.utm_sources = [
        {"source": s, "count": c, "unique_ips": len(utm_source_unique[s])}
        for s, c in utm_source_counter.most_common(10)
    ]
    summary.utm_campaigns = [
        {"campaign": s, "count": c}
        for s, c in utm_campaign_counter.most_common(10)
    ]
    summary.status_codes = [
        {"status": code, "count": c}
        for code, c in sorted(status_counter.items())
    ]
    # by_day sorted oldest → newest for chart consumption
    summary.by_day = [
        {"day": day, **counts}
        for day, counts in sorted(by_day.items())
    ]
    # Most recent slow requests, capped — a noisy slow path can dominate
    summary.slow_requests = sorted(
        slow_requests,
        key=lambda r: r["ts"],
        reverse=True,
    )[:25]
    return summary


async def get_traffic_summary(
    log_dir: str,
    days: int = 7,
) -> TrafficSummary:
    """Public entrypoint — async so it doesn't block the event loop on disk I/O.

    `days` is interpreted as a rolling window ending at "now". A safety
    cap of 30 days matches our log retention; requesting more is silently
    clamped.
    """
    days = max(1, min(int(days), 30))
    until = datetime.now(tz=timezone.utc)
    since = until - timedelta(days=days)
    cache_key = (log_dir, since.isoformat()[:13], until.isoformat()[:13])  # hour-grain key
    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]
    # Run the parse off the event loop
    summary = await asyncio.to_thread(
        _parse_logs_sync,
        Path(log_dir),
        since,
        until,
    )
    async with _cache_lock:
        _cache[cache_key] = (time.time(), summary)
    return summary

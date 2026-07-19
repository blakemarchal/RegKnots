"""Live-context injectors — 2026-07-19 (Wk3, feature de-siloing).

The product's freshest data lived outside chat: corpus-ingest history
powered /me/compliance-changelog (a card on a page nobody visits) and
the NOAA whale-zone windows powered /whale-zones. Asking the CHAT
"what changed in the regs recently?" or "which whale zones are active?"
produced a hedge — retrieval finds regulation TEXT, not operational
state. For a compliance officer the chat IS the product; every answer
that ends in "I can't see that" burns trust.

Pattern: intent regex → compact data block → appended to the synthesis
prompt alongside (never replacing) normal retrieval context. Each block
carries its own usage NOTE so no system-prompt change is required.
False-positive cost is a few hundred prompt tokens — harmless.

Two injectors:
  1. Reg-change intent → recent-ingest summary. Built HERE (needs only
     the pool the engine already holds); chat_with_progress() detects
     and injects automatically.
  2. Whale-zone intent → active-SMA summary. The SMA calendar lives in
     the API layer (app/data/whale_sma_zones.py), so the chat router
     builds that block and passes it via live_context_block. The
     detection regex lives here so both layers share one definition.
"""
from __future__ import annotations

import logging
import re
from datetime import date

import asyncpg

logger = logging.getLogger(__name__)

# ── Intent detection ────────────────────────────────────────────────────

# Temporal-change phrasing. Requires an explicit recency signal so
# "new construction requirements for tank vessels" (topic question)
# doesn't trip it — but "what changed recently", "any new regs this
# month", "latest amendments" do.
_REG_CHANGE_RE = re.compile(
    r"""(?ix)
    (
      \bwhat(?:'s|\s+is|\s+has|\s+have)?\s+(?:recently\s+)?
        (?:changed|been\s+(?:updated|added|amended))\b
      | \brecent(?:ly)?\s+(?:change|update|amendment|addition|revision)s?\b
      | \b(?:new|latest|recent)\s+(?:reg(?:ulation)?s?|rules?|amendments?|updates?|requirements?)\s+
        (?:in\s+the\s+)?(?:last|past|this)\s+(?:few\s+)?(?:days?|weeks?|months?|quarter|year)\b
      | \bwhat'?s\s+new\b
      | \bchange\s?log\b
      | \b(?:last|past|this)\s+(?:week|month|quarter)'?s?\s+(?:reg(?:ulation)?|rule)\w*\s+(?:change|update)s?\b
      | \bany\s+(?:new|recent)\s+(?:reg(?:ulation)?s?|amendments?|updates?)\b
    )
    """,
)

_WHALE_ZONE_RE = re.compile(
    r"""(?ix)
    (
      \bwhale\s+(?:zone|area|sma)s?\b
      | \bseasonal\s+management\s+areas?\b
      | \bright\s+whale\b
      | \b(?:active\s+)?smas?\s+(?:active|in\s+effect)\b
      | \b10[-\s]?knot\s+(?:rule|restriction|speed)\b
    )
    """,
)


def detect_live_context(query: str) -> str | None:
    """Return 'reg_changes' | 'whale_zones' | None for this query."""
    if _WHALE_ZONE_RE.search(query):
        return "whale_zones"
    if _REG_CHANGE_RE.search(query):
        return "reg_changes"
    return None


def window_days_for_query(query: str, default: int = 30) -> int:
    """Pick the lookback window from the query's own temporal language."""
    q = query.lower()
    if re.search(r"\b(today|yesterday|48 hours|few days)\b", q):
        return 7
    if "week" in q:
        return 7
    if "quarter" in q or "90 day" in q:
        return 90
    if "year" in q or "12 month" in q:
        return 365
    if "month" in q or "30 day" in q:
        return 30
    return default


# ── Injector 1: recent corpus changes ───────────────────────────────────

async def build_reg_changes_block(
    pool: asyncpg.Pool, query: str, *, max_sections: int = 12,
) -> str | None:
    """Compact summary of recent corpus ingests, grouped by source.

    Returns None on empty window or any error (injection is always
    optional — a failure must never break the chat turn).
    """
    days = window_days_for_query(query)
    try:
        group_rows = await pool.fetch(
            """
            SELECT source, COUNT(*) AS n,
                   MIN(created_at)::date AS first_seen,
                   MAX(created_at)::date AS last_seen
            FROM regulations
            WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
            GROUP BY source
            ORDER BY n DESC
            LIMIT 15
            """,
            str(days),
        )
        if not group_rows:
            return (
                f"LIVE CORPUS UPDATE DATA (as of {date.today().isoformat()}, "
                f"window: last {days} days):\n"
                f"No sections were added or updated in the RegKnots corpus in "
                f"this window.\n"
                f"NOTE: The user is asking about recent regulatory changes. "
                f"State plainly that no corpus updates landed in the last "
                f"{days} days, and offer the most recent known changes if they "
                f"widen the window. Do not fabricate changes.\n"
            )

        sample_rows = await pool.fetch(
            """
            SELECT DISTINCT ON (section_number)
                   source, section_number, section_title, created_at::date AS ingested
            FROM regulations
            WHERE created_at > NOW() - ($1 || ' days')::INTERVAL
            ORDER BY section_number, created_at DESC
            LIMIT $2
            """,
            str(days), max_sections,
        )

        total = sum(r["n"] for r in group_rows)
        lines = [
            f"LIVE CORPUS UPDATE DATA (as of {date.today().isoformat()}, "
            f"window: last {days} days) — {total} section(s) added/updated:",
        ]
        for r in group_rows:
            span = (
                str(r["last_seen"])
                if r["first_seen"] == r["last_seen"]
                else f"{r['first_seen']} → {r['last_seen']}"
            )
            lines.append(f"- {r['source']}: {r['n']} sections ({span})")
        if sample_rows:
            lines.append("Representative sections:")
            for r in sample_rows:
                lines.append(
                    f"  • {r['section_number']} — "
                    f"{(r['section_title'] or '')[:90]} [{r['source']}, {r['ingested']}]"
                )
        lines.append(
            "NOTE: These are additions/updates to the RegKnots corpus (ingest "
            "dates shown), which can lag the regulator's publication date. "
            "Answer the user's what-changed question from this data: lead with "
            "the most operationally relevant updates, cite section numbers "
            "normally, and be clear that effective dates come from the "
            "regulation text itself. Do not invent changes not listed here."
        )
        return "\n".join(lines) + "\n"
    except Exception as exc:  # noqa: BLE001 — injection must never break chat
        logger.warning("reg-changes live-context build failed: %s", exc)
        return None

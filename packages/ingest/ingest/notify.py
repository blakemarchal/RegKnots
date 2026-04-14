"""
Auto-notification hook for the ingest pipeline.

Inserts a row into the `notifications` table (defined by Alembic 0031
in apps/api) whenever an ingest run has actually changed the database.
Also sends immediate email alerts to users who have opted in to alerts
for the updated source.

The table schema is owned by apps/api; this module treats it as an
unowned integration point and writes via raw asyncpg. It deliberately
does NOT import from apps/api to avoid coupling packages.

Gate for notification creation AND email alerts:
  - `new_or_modified_chunks > 0`  → at least one chunk has a content hash
    the DB didn't have before this run (i.e. new or edited section).

If a run produces 0 chunks, 0 upserts, or only re-embedded unchanged
content, no notification is created and no emails are sent.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

import asyncpg

from ingest.models import IngestResult

logger = logging.getLogger(__name__)


# Friendly labels per source for notification titles. Unknown sources fall
# back to a generic title built from the source tag.
_SOURCE_LABELS: dict[str, tuple[str, str]] = {
    # source → (short title, type descriptor used in body)
    "cfr_33": ("CFR Title 33 Updated", "CFR Title 33 (Navigation and Navigable Waters)"),
    "cfr_46": ("CFR Title 46 Updated", "CFR Title 46 (Shipping)"),
    "cfr_49": ("CFR Title 49 Updated", "CFR Title 49 (Transportation)"),
    "nvic":   ("New USCG NVIC Published", "NVIC (Navigation and Vessel Inspection Circulars)"),
    "colregs": ("COLREGs Updated", "COLREGs (International/Inland Navigation Rules)"),
    "solas":   ("SOLAS Updated", "SOLAS (Safety of Life at Sea)"),
    "solas_supplement": (
        "SOLAS Supplement Amendment Added",
        "SOLAS supplement (MSC resolution amendments)",
    ),
    "stcw":   ("STCW Updated", "STCW (Training, Certification and Watchkeeping)"),
    "stcw_supplement": (
        "STCW Supplement Amendment Added",
        "STCW supplement (MSC resolution amendments)",
    ),
    "ism":    ("ISM Code Updated", "ISM Code (Safe Operation of Ships)"),
}


def _build_message(result: IngestResult) -> str:
    """Build a short human-readable summary of what changed."""
    changed = result.new_or_modified_chunks
    delta = result.net_chunk_delta
    today = datetime.now(timezone.utc).strftime("%B %d, %Y")

    if delta > 0 and changed > delta:
        # Some new sections AND some modified
        return (
            f"{delta} new sections added, {changed - delta} updated "
            f"as of {today}. Ask me about the latest requirements."
        )
    if delta > 0:
        return (
            f"{delta} new sections added as of {today}. "
            f"Ask me about the latest requirements."
        )
    if delta < 0:
        removed = -delta
        kept = max(0, changed)
        if kept:
            return (
                f"{removed} sections removed, {kept} updated "
                f"as of {today}."
            )
        return f"{removed} sections removed as of {today}."
    # delta == 0 — pure content updates to existing sections
    return (
        f"{changed} sections updated with revised language "
        f"as of {today}. Ask me about the latest requirements."
    )


async def _send_immediate_alerts(
    pool: asyncpg.Pool, source: str, title: str, body: str,
) -> int:
    """Email users who have opted in to immediate alerts for this source.

    Uses the Resend email service via the apps/api email module.
    This creates a soft dependency on apps/api at runtime, but since
    notify.py only runs inside the ingest CLI which already runs from
    the apps/api virtualenv, this is safe.

    Returns the number of emails sent.
    """
    try:
        # Import email utilities from apps/api — available in the same venv.
        import resend
        # We need the Resend API key. Read it from env since we can't import
        # apps/api config without coupling.
        import os
        api_key = os.environ.get("RESEND_API_KEY", "")
        if not api_key:
            logger.warning("notify: RESEND_API_KEY not set — skipping immediate alerts")
            return 0
        resend.api_key = api_key
    except ImportError:
        logger.warning("notify: resend not installed — skipping immediate alerts")
        return 0

    # Map supplement sources to their parent for matching user preferences.
    # Users subscribe to "solas" and get alerts for both solas and solas_supplement.
    _SOURCE_PREF_MAP = {
        "solas_supplement": "solas",
        "stcw_supplement": "stcw",
        "ism_supplement": "ism",
    }
    pref_source = _SOURCE_PREF_MAP.get(source, source)

    try:
        rows = await pool.fetch(
            """
            SELECT email, full_name, notification_preferences
            FROM users
            WHERE (subscription_tier != 'free' OR trial_ends_at > NOW())
            """
        )
    except Exception as exc:
        logger.error("notify: failed to query users for alerts: %s", exc)
        return 0

    sent = 0
    from_email = "RegKnot <hello@mail.regknots.com>"

    for row in rows:
        prefs = row["notification_preferences"] or {}
        if isinstance(prefs, str):
            prefs = json.loads(prefs)

        # Check if user has this source in their alert list
        alert_sources = prefs.get("reg_alert_sources", [])
        if pref_source not in alert_sources:
            continue

        try:
            first_name = (row["full_name"] or "").split()[0] if row["full_name"] else "Mariner"
            resend.Emails.send({
                "from": from_email,
                "to": [row["email"]],
                "subject": f"{title} — RegKnot",
                "html": _build_alert_html(first_name, title, body),
            })
            sent += 1
            logger.info("notify: sent immediate alert to %s for %s", row["email"], source)
            # Throttle to stay under Resend's 5 req/s limit
            await asyncio.sleep(0.25)
        except Exception as exc:
            logger.error("notify: failed to send alert to %s: %s", row["email"], exc)

    return sent


def _build_alert_html(first_name: str, title: str, body: str) -> str:
    """Build a simple alert email HTML."""
    import html as html_lib
    safe_first = html_lib.escape(first_name)
    safe_title = html_lib.escape(title)
    safe_body = html_lib.escape(body)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{ margin: 0; padding: 0; background-color: #0a0e1a; font-family: 'Courier New', Courier, monospace; }}
    .wrapper {{ max-width: 560px; margin: 0 auto; padding: 40px 24px; }}
    .card {{ background-color: #111827; border: 1px solid rgba(255,255,255,0.08); border-radius: 16px; padding: 36px 32px; }}
    .logo-text {{ font-family: Arial, sans-serif; font-size: 22px; font-weight: 900; letter-spacing: 0.2em; text-transform: uppercase; color: #f0ece4; margin-bottom: 32px; }}
    .logo-text span {{ color: #2dd4bf; }}
    h1 {{ font-family: Arial, sans-serif; font-size: 24px; font-weight: 900; color: #f0ece4; margin: 0 0 16px; }}
    p {{ font-size: 14px; line-height: 1.7; color: #6b7594; margin: 0 0 16px; }}
    .update-box {{ background-color: #0d1225; border: 1px solid rgba(45,212,191,0.2); border-radius: 10px; padding: 20px; margin: 16px 0; }}
    .update-box p {{ color: #f0ece4; margin: 0; font-size: 14px; }}
    .cta {{ display: inline-block; margin: 8px 0 24px; padding: 14px 28px; background-color: #2dd4bf; color: #0a0e1a; font-family: 'Courier New', monospace; font-size: 13px; font-weight: 700; text-decoration: none; border-radius: 10px; letter-spacing: 0.1em; text-transform: uppercase; }}
    .disclaimer {{ font-size: 11px; color: rgba(107,117,148,0.6); line-height: 1.6; margin: 0; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="card">
      <div class="logo-text">Reg<span>Knot</span></div>
      <h1>{safe_title}</h1>
      <p>Hey {safe_first},</p>
      <div class="update-box"><p>{safe_body}</p></div>
      <p>This regulation source has been updated in the RegKnot database. Ask me about the changes to understand how they affect your vessel.</p>
      <a href="https://regknots.com" class="cta">Ask About This Update</a>
      <p style="font-size:12px; color:rgba(107,117,148,0.7); margin-top:8px;">You're receiving this because you have alerts enabled for this source. Adjust your preferences in Account settings.</p>
      <hr style="border:none; border-top:1px solid rgba(255,255,255,0.08); margin:24px 0;">
      <p class="disclaimer">RegKnot is a navigation aid only — not legal advice.</p>
    </div>
  </div>
</body>
</html>"""


async def create_regulation_update_notification(
    pool: asyncpg.Pool,
    result: IngestResult,
) -> str | None:
    """Insert a notifications row if this ingest run actually changed content.

    Also sends immediate email alerts to users who have opted in for the
    updated source. Emails only fire when there are actual content changes
    (new_or_modified_chunks > 0), never on no-op re-checks.

    Returns the new notification id (str) when a row is created, or None if
    the run had no real changes and no notification was needed.

    Silently logs and returns None on insertion errors — a notification
    failure should never abort an otherwise-successful ingest.
    """
    if result.new_or_modified_chunks <= 0:
        logger.debug(
            "notify: skipping %s — no new/modified chunks (upserts=%d, skipped=%d)",
            result.source, result.upserts, result.chunks_skipped,
        )
        return None

    label = _SOURCE_LABELS.get(
        result.source,
        (f"{result.source} updated", result.source),
    )
    title = label[0]
    body = _build_message(result)

    # 1. Insert in-app notification banner
    notif_id = None
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO notifications
                (title, body, notification_type, source, is_active)
            VALUES ($1, $2, 'regulation_update', $3, true)
            RETURNING id
            """,
            title,
            body,
            result.source,
        )
        notif_id = str(row["id"])
        logger.info(
            "notify: created notification %s for %s "
            "(new_or_modified=%d, net_delta=%d)",
            notif_id, result.source,
            result.new_or_modified_chunks, result.net_chunk_delta,
        )
    except Exception as exc:
        # Never raise — a missing `notifications` table (e.g. during local
        # testing against an older DB) should not take down the ingest run.
        logger.error(
            "notify: failed to insert notification for %s: %s",
            result.source, exc,
        )

    # 2. Send immediate email alerts to opted-in users
    try:
        sent = await _send_immediate_alerts(pool, result.source, title, body)
        if sent > 0:
            logger.info(
                "notify: sent %d immediate alert email(s) for %s",
                sent, result.source,
            )
    except Exception as exc:
        # Email failures should never abort ingest
        logger.error(
            "notify: immediate alert emails failed for %s: %s",
            result.source, exc,
        )

    return notif_id

"""
Auto-notification hook for the ingest pipeline.

Inserts a row into the `notifications` table (defined by Alembic 0031
in apps/api) whenever an ingest run has actually changed the database.

The table schema is owned by apps/api; this module treats it as an
unowned integration point and writes via raw asyncpg. It deliberately
does NOT import from apps/api to avoid coupling packages.

Gate for notification creation:
  - `new_or_modified_chunks > 0`  → at least one chunk has a content hash
    the DB didn't have before this run (i.e. new or edited section).

If a run produces 0 chunks, 0 upserts, or only re-embedded unchanged
content, no notification is created (no-op runs stay silent).
"""

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


async def create_regulation_update_notification(
    pool: asyncpg.Pool,
    result: IngestResult,
) -> str | None:
    """Insert a notifications row if this ingest run actually changed content.

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
        return notif_id
    except Exception as exc:
        # Never raise — a missing `notifications` table (e.g. during local
        # testing against an older DB) should not take down the ingest run.
        logger.error(
            "notify: failed to insert notification for %s: %s",
            result.source, exc,
        )
        return None

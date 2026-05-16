"""IMO → class society auto-lookup (D6.94 Sprint A).

The vessels POST/PATCH path calls ``auto_populate_classification_society``
when a vessel record has an IMO but no user-set classification_society
yet. The helper checks the iacs_ships_in_class lookup table (populated
weekly from the IACS Vessels-in-Class CSV) and returns the normalized
society code so the caller can write it back with source='iacs_lookup'.

We never overwrite a 'user'-source value — once the user picks a society
explicitly, that's the truth. We only fill NULLs.

The vessels.imo_mmsi column is a freeform string that can hold either
an IMO number (7 digits) or an MMSI (9 digits). The IACS CSV is keyed
by IMO; MMSI inputs return None.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

import asyncpg

logger = logging.getLogger(__name__)

# IMO numbers are 7 digits, sometimes prefixed with "IMO" or "IMO ".
_IMO_RE = re.compile(r"^(?:IMO\s*)?(\d{7})$", re.IGNORECASE)


def parse_imo(imo_mmsi: Optional[str]) -> Optional[int]:
    """Extract the IMO integer from a freeform vessels.imo_mmsi value.

    Returns None for MMSI inputs (9 digits), empty strings, or anything
    that doesn't look like an IMO. Callers should treat None as "no
    lookup possible" and fall through to the user prompt.
    """
    if not imo_mmsi:
        return None
    s = imo_mmsi.strip()
    m = _IMO_RE.match(s)
    if not m:
        return None
    return int(m.group(1))


async def lookup_society_by_imo(
    pool: asyncpg.Pool, imo: int,
) -> Optional[str]:
    """Return the normalized society code for an IMO, or None on miss.

    Hits the iacs_ships_in_class cache only — no upstream API calls per
    request. The cache is refreshed weekly by
    scripts/refresh_iacs_ships_in_class.py.
    """
    return await pool.fetchval(
        "SELECT society_normalized FROM iacs_ships_in_class "
        "WHERE imo = $1 AND society_normalized IS NOT NULL",
        imo,
    )


async def auto_populate_classification_society(
    conn: asyncpg.Connection,
    vessel_id,
    imo_mmsi: Optional[str],
) -> Optional[str]:
    """If the vessel has no classification_society yet, try the IACS
    lookup and write it back with source='iacs_lookup'.

    Returns the society code that was set, or None if no lookup was
    possible. Idempotent — re-running on a vessel that already has a
    society is a no-op (we never overwrite an existing value).
    """
    imo = parse_imo(imo_mmsi)
    if imo is None:
        return None

    # Don't overwrite a user-set value, even if IACS disagrees.
    existing = await conn.fetchrow(
        "SELECT classification_society, classification_society_source "
        "FROM vessels WHERE id = $1",
        vessel_id,
    )
    if existing is None:
        return None
    if existing["classification_society"] is not None:
        return existing["classification_society"]

    society = await conn.fetchval(
        "SELECT society_normalized FROM iacs_ships_in_class "
        "WHERE imo = $1 AND society_normalized IS NOT NULL",
        imo,
    )
    if society is None:
        return None

    await conn.execute(
        "UPDATE vessels "
        "SET classification_society = $1, "
        "    classification_society_source = 'iacs_lookup' "
        "WHERE id = $2 "
        "AND classification_society IS NULL",
        society, vessel_id,
    )
    logger.info(
        "class_society: auto-populated vessel %s with %s (IMO %s)",
        vessel_id, society, imo,
    )
    return society

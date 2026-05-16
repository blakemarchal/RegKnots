"""Refresh the iacs_ships_in_class lookup table from IACS' public weekly CSV.

Sprint D6.94 — RegKnots needs an IMO → class society lookup so the
vessel profile auto-populates classification_society when a user
enters an IMO. IACS publishes a public ZIP every Wednesday at
https://iacs.org.uk/membership/vessels-in-class/, containing a
semicolon-delimited CSV of every IMO classed by an IACS member
society (~61k unique vessels, ~95% of global merchant tonnage).

This script:

  1. Fetches the vessels-in-class HTML and extracts the latest
     S3 ZIP URL from the embedded Nuxt JSON.
  2. Downloads the ZIP, extracts the single CSV.
  3. Parses each row, normalizing the upstream society code
     (LRS → LR, NV → DNV, NKK → ClassNK, etc.) into the same
     enum used by vessels.classification_society.
  4. UPSERTs into iacs_ships_in_class keeping the row with the
     latest date_of_latest_status per IMO (some IMOs appear in
     multiple snapshot rows when class transferred).

Usage:
    uv run python scripts/refresh_iacs_ships_in_class.py
    uv run python scripts/refresh_iacs_ships_in_class.py --url <override>
    uv run python scripts/refresh_iacs_ships_in_class.py --dry-run

Run weekly via systemd timer (regknots-refresh-weekly.service —
add an entry to scripts/corpus_refresh.sh after this script lands).
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import io
import logging
import os
import re
import sys
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import asyncpg
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("iacs_refresh")


IACS_PAGE = "https://iacs.org.uk/membership/vessels-in-class/"

# Upstream society code → vessels.classification_society enum value.
# Codes observed in the 2026-05-15 snapshot: NKK, BV, LRS, NV, ABS,
# RINA, CCS, KR, IRS, PRS, TLV (Türk Loydu — not an IACS full member;
# kept as 'other'), CRS.
SOCIETY_MAP: dict[str, str] = {
    "ABS":  "ABS",
    "LRS":  "LR",
    "LR":   "LR",
    "NV":   "DNV",
    "DNV":  "DNV",
    "DNVL": "DNV",   # legacy DNV-GL code, harmless to map preemptively
    "NKK":  "ClassNK",
    "NK":   "ClassNK",
    "BV":   "BV",
    "KR":   "KR",
    "CCS":  "CCS",
    "RINA": "RINA",
    "CRS":  "CRS",
    "IRS":  "IRS",
    "PRS":  "PRS",
    # Non-full-member abbreviations seen in IACS feed → 'other'
    "TLV":  "other",
}


def _fetch_page_html(url: str) -> str:
    """Fetch the IACS vessels-in-class HTML. UA header required —
    Cloudflare blocks default httpx UA on some routes."""
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "Mozilla/5.0 RegKnots"})
        r.raise_for_status()
        return r.text


# The IACS site is a Nuxt SPA; the download URLs live inside
# window.__NUXT__ JSON, in download_items[].file fields. Pull them out
# via a regex against the rendered HTML — robust enough for the
# foreseeable feed format.
_FILE_URL_RE = re.compile(
    r'file:"(https:\\u002F\\u002Fiacs\.s3\.[^"]+EquasisToIACS[^"]+\.zip)"'
)


def _latest_zip_url(html: str) -> Optional[str]:
    matches = _FILE_URL_RE.findall(html)
    if not matches:
        return None
    # Files are listed newest-first in the HTML; first hit is the latest.
    raw = matches[0]
    # Nuxt encodes "/" as "/"; un-escape.
    return raw.replace("\\u002F", "/")


def _download_csv(url: str) -> tuple[str, bytes]:
    """Download the ZIP and return (basename_of_csv_inside, csv_bytes)."""
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        r = client.get(url, headers={"User-Agent": "Mozilla/5.0 RegKnots"})
        r.raise_for_status()
        data = r.content
    z = zipfile.ZipFile(io.BytesIO(data))
    names = z.namelist()
    if not names:
        raise RuntimeError(f"empty zip from {url}")
    # Prefer .csv; falls back to first entry.
    csv_name = next((n for n in names if n.lower().endswith(".csv")), names[0])
    return csv_name, z.read(csv_name)


def _parse_date(s: str) -> Optional[date]:
    """IACS uses YYYYMMDD as strings; blank values are dropped."""
    if not s or not s.strip():
        return None
    s = s.strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return datetime.strptime(s, "%Y%m%d").date()
    except ValueError:
        return None


def _parse_ship_name(raw: str) -> Optional[str]:
    """Upstream ship-name column has a trailing (DD/MM/YY) snapshot tag
    appended in parens. Strip it for cleaner display."""
    if not raw:
        return None
    return re.sub(r"\s*\(\d{2}/\d{2}/\d{2}\)\s*$", "", raw).strip() or None


def _iter_rows(csv_bytes: bytes):
    """Parse the semicolon-delimited CSV. Yields dicts keyed by header."""
    # IACS CSV is UTF-8 with no BOM and uses ';' as separator. Some
    # historical rows ship CP-1252 mojibake on non-ASCII ship names; we
    # decode lossy to avoid crashing the whole import on one bad row.
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    for row in reader:
        yield row


def _normalize_society(code: str) -> Optional[str]:
    """Map IACS upstream code → vessels.classification_society enum."""
    if not code:
        return None
    return SOCIETY_MAP.get(code.strip().upper())


async def _upsert_rows(
    conn: asyncpg.Connection, rows: list[dict], snapshot_source_file: str,
) -> int:
    """Bulk upsert IACS rows, keeping the row with the latest
    date_of_latest_status per IMO when duplicates appear in the feed.

    Returns the number of distinct IMOs upserted.
    """
    # Dedupe in-memory first; cheaper than relying on ON CONFLICT to
    # arbitrate between batched conflicts on the same key.
    best: dict[int, dict] = {}
    for r in rows:
        imo_s = (r.get("IMO") or "").strip()
        if not imo_s or not imo_s.isdigit():
            continue
        imo = int(imo_s)
        last = _parse_date(r.get("DATE OF LATEST STATUS", ""))
        existing = best.get(imo)
        if existing is None:
            best[imo] = r
            continue
        # Prefer the row with the newer DATE OF LATEST STATUS.
        existing_last = _parse_date(existing.get("DATE OF LATEST STATUS", ""))
        if last and (existing_last is None or last > existing_last):
            best[imo] = r

    sql = """
        INSERT INTO iacs_ships_in_class (
            imo, society_raw, society_normalized, ship_name,
            date_of_survey, date_of_next_survey, date_of_latest_status,
            status, status_reason, snapshot_source_file, refreshed_at
        )
        VALUES (
            $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW()
        )
        ON CONFLICT (imo) DO UPDATE SET
            society_raw          = EXCLUDED.society_raw,
            society_normalized   = EXCLUDED.society_normalized,
            ship_name            = EXCLUDED.ship_name,
            date_of_survey       = EXCLUDED.date_of_survey,
            date_of_next_survey  = EXCLUDED.date_of_next_survey,
            date_of_latest_status = EXCLUDED.date_of_latest_status,
            status               = EXCLUDED.status,
            status_reason        = EXCLUDED.status_reason,
            snapshot_source_file = EXCLUDED.snapshot_source_file,
            refreshed_at         = NOW()
    """

    rows_data = []
    for imo, r in best.items():
        society_raw = (r.get("CLASS") or "").strip()
        rows_data.append((
            imo,
            society_raw,
            _normalize_society(society_raw),
            _parse_ship_name(r.get("SHIP NAME", "")),
            _parse_date(r.get("DATE OF SURVEY", "")),
            _parse_date(r.get("DATE OF NEXT SURVEY", "")),
            _parse_date(r.get("DATE OF LATEST STATUS", "")),
            (r.get("STATUS") or "").strip() or None,
            (r.get("REASON FOR THE STATUS") or "").strip() or None,
            snapshot_source_file,
        ))

    # Batch via executemany for speed.
    await conn.executemany(sql, rows_data)
    return len(rows_data)


async def _async_main(args) -> int:
    # ── Discover the latest ZIP URL ────────────────────────────────────────
    if args.url:
        zip_url = args.url
        logger.info("Using explicit URL: %s", zip_url)
    else:
        logger.info("Fetching IACS page %s", IACS_PAGE)
        html = _fetch_page_html(IACS_PAGE)
        zip_url = _latest_zip_url(html)
        if zip_url is None:
            logger.error("Could not extract a download URL from %s", IACS_PAGE)
            return 1
        logger.info("Latest ZIP URL: %s", zip_url)

    # ── Download + parse ───────────────────────────────────────────────────
    csv_name, csv_bytes = _download_csv(zip_url)
    logger.info("Downloaded %s (%d bytes)", csv_name, len(csv_bytes))

    rows = list(_iter_rows(csv_bytes))
    logger.info("Parsed %d rows from CSV", len(rows))

    # Quick society distribution sanity check.
    society_counts: dict[str, int] = {}
    for r in rows:
        c = (r.get("CLASS") or "").strip().upper()
        society_counts[c] = society_counts.get(c, 0) + 1
    logger.info("Society distribution (raw): %s", dict(sorted(
        society_counts.items(), key=lambda kv: -kv[1]
    )))

    if args.dry_run:
        logger.info("--dry-run set, skipping DB writes")
        return 0

    # asyncpg uses 'postgresql://', not the SQLAlchemy dialect form.
    dsn = args.database_url.replace("postgresql+asyncpg://", "postgresql://")

    # ── Upsert ────────────────────────────────────────────────────────────
    conn = await asyncpg.connect(dsn)
    try:
        n = await _upsert_rows(conn, rows, snapshot_source_file=csv_name)
    finally:
        await conn.close()
    logger.info("Upserted %d distinct IMOs into iacs_ships_in_class", n)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url", help="Direct ZIP URL (bypass HTML scrape)", default=None,
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Parse only — skip DB writes.",
    )
    parser.add_argument(
        "--database-url",
        default=os.environ.get("DATABASE_URL", "postgresql://regknots:regknots@localhost:5432/regknots"),
        help="Postgres DSN (default reads DATABASE_URL env var).",
    )
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())

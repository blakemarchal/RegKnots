"""Seed the nmc_monitor_seen_urls table with every URL currently on NMC.

Run ONCE immediately after applying migration 0046 on any environment
that hasn't run the Sprint-D1 scraper yet. After seeding, the first
scheduled run will produce ~zero findings — only genuinely new PDFs
since today will show up in the admin digest.

Without this seed step the first post-migration run would re-surface
the entire NMC document catalog as "new" (~220+ documents) in a single
admin email. That's not destructive anymore (no user-facing
notifications after D1) but it's noisy for the Owner.

Usage (on the VPS):
    cd /opt/RegKnots
    uv run python scripts/seed_nmc_monitor.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import sys

import asyncpg
import requests

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("seed_nmc_monitor")


_NMC_SOURCES = [
    {"name": "NMC Announcements", "url": "https://www.dco.uscg.mil/nmc/announcements/"},
    {"name": "NMC Policy & Regulations", "url": "https://www.dco.uscg.mil/nmc/policy_regulations/"},
    {"name": "NMC Medical/Physical Guidelines", "url": "https://www.dco.uscg.mil/nmc/medical/"},
]

_NMC_PDF_RE = re.compile(
    r'href=["\']([^"\']*?/Portals/9/NMC/[^"\']*?\.pdf)["\']',
    re.IGNORECASE,
)


def _normalize(pdf_path: str) -> str:
    if pdf_path.startswith("/"):
        return f"https://www.dco.uscg.mil{pdf_path}"
    if not pdf_path.startswith("http"):
        return f"https://www.dco.uscg.mil/{pdf_path}"
    return pdf_path


def _prettify(pdf_url: str) -> str:
    filename = pdf_url.rsplit("/", 1)[-1].replace("%20", " ").replace("_", " ")
    return filename[:-4] if filename.lower().endswith(".pdf") else filename


async def main() -> int:
    dsn = os.environ.get("REGKNOTS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn:
        logger.error(
            "REGKNOTS_DATABASE_URL (or DATABASE_URL) env var required. "
            "Source from /opt/RegKnots/.env before running."
        )
        return 2

    dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")

    rows_to_insert: list[tuple[str, str, str]] = []
    for source in _NMC_SOURCES:
        try:
            resp = requests.get(
                source["url"],
                timeout=30,
                headers={"User-Agent": "RegKnot NMC Seed/1.0"},
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("Failed to scrape %s: %s", source["name"], exc)
            continue

        page_urls = set()
        for match in _NMC_PDF_RE.finditer(resp.text):
            url = _normalize(match.group(1))
            if url in page_urls:
                continue
            page_urls.add(url)
            rows_to_insert.append((url, _prettify(url), source["name"]))
        logger.info("Scraped %s: %d unique URLs", source["name"], len(page_urls))

    logger.info("Total URLs collected across all pages: %d", len(rows_to_insert))

    conn = await asyncpg.connect(dsn)
    try:
        existing = await conn.fetchval("SELECT COUNT(*) FROM nmc_monitor_seen_urls")
        logger.info("Existing rows in nmc_monitor_seen_urls: %d", existing)

        inserted = await conn.executemany(
            """
            INSERT INTO nmc_monitor_seen_urls (url, filename, source_page)
            VALUES ($1, $2, $3)
            ON CONFLICT (url) DO NOTHING
            """,
            rows_to_insert,
        )
        # executemany returns None in asyncpg; recount to confirm
        new_total = await conn.fetchval("SELECT COUNT(*) FROM nmc_monitor_seen_urls")
        logger.info(
            "Seed complete. Rows before=%d after=%d added=%d",
            existing, new_total, new_total - existing,
        )
    finally:
        await conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

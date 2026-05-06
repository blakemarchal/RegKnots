"""Scheduled NMC corpus refresh — discovers new PDFs at the canonical NMC
URLs, downloads any we don't already have to data/raw/nmc/, and triggers
a re-ingest if anything new was found.

Sprint D6.75 — Karynn-caught corpus staleness motivated this. Static-only
ingest let us drift 4+ months behind the NMC ASAP portal launch (2026-01-26)
because nothing was scheduled to refresh the corpus. This script + the
companion systemd timer (regknots-nmc-refresh.timer, runs weekly) keep
the NMC corpus current going forward.

Architecture:
  1. Scrape the 3 canonical NMC landing pages for PDF links (the same
     pages seed_nmc_monitor.py watches). Browser-style headers required
     because the dco.uscg.mil Akamai edge filters out plain curl/python
     requests as suspected bots.
  2. Diff against files already in data/raw/nmc/ (by basename, lowercased).
  3. Download any new PDFs into data/raw/nmc/ with a safe filename
     (basename only, no path traversal).
  4. If at least one new PDF landed, run the nmc_policy and nmc_checklist
     ingests to add the new chunks. Skipping ingest when nothing changed
     keeps the weekly run cheap.
  5. Update nmc_monitor_seen_urls so the existing admin-facing monitor
     doesn't re-flag the new URLs as "new".

Exit codes:
  0  — success (with or without new PDFs found)
  1  — at least one URL fetch failed AND no new PDFs landed
  2  — ingest command failed

Logging: stdout (captured by journald via the systemd unit). Anything at
WARNING or above bubbles to admin via the existing notify pathways if we
add an `--alert` flag later. For now, journalctl -u regknots-nmc-refresh
shows the run history.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

import asyncpg
import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("refresh_nmc_corpus")


_NMC_LANDING_PAGES = (
    "https://www.dco.uscg.mil/nmc/announcements/",
    "https://www.dco.uscg.mil/nmc/policy_regulations/",
    "https://www.dco.uscg.mil/nmc/medical/",
)

# Akamai filters out plain curl/requests; full browser header set required.
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
}

_PDF_LINK_RE = re.compile(
    r'href=["\']([^"\']*?/Portals/9/NMC/[^"\']*?\.pdf)(?:\?[^"\']*)?["\']',
    re.IGNORECASE,
)

# Filename-cleanup: lowercase, strip illegal chars, collapse spaces. We don't
# need to preserve the exact source filename — the ingest pipeline uses our
# local basename to look up _DOC_META, so adding an entry to nmc.py is the
# adoption gate for any new file. This script only DOWNLOADS files; it
# doesn't auto-add them to the ingest set, by design (so a rogue PDF on
# the NMC site can't silently change the corpus).
_FILENAME_SANITIZE = re.compile(r"[^A-Za-z0-9._-]+")


def _normalize_url(url: str) -> str:
    if url.startswith("/"):
        return f"https://www.dco.uscg.mil{url}"
    if not url.startswith("http"):
        return f"https://www.dco.uscg.mil/{url}"
    return url


def _safe_basename(url: str) -> str:
    name = url.rsplit("/", 1)[-1]
    name = name.split("?", 1)[0]              # strip query string
    name = name.replace("%20", "_").replace(" ", "_")
    name = _FILENAME_SANITIZE.sub("_", name)
    return name.lower()


def _scrape_landing(url: str, session: requests.Session) -> set[str]:
    """Fetch a landing page and return the set of PDF URLs it links to."""
    try:
        resp = session.get(url, headers=_BROWSER_HEADERS, timeout=30)
    except Exception as exc:
        logger.warning("Scrape failed for %s: %s", url, exc)
        return set()
    if resp.status_code != 200:
        logger.warning("Scrape %s returned status %d", url, resp.status_code)
        return set()
    found = {_normalize_url(m) for m in _PDF_LINK_RE.findall(resp.text)}
    logger.info("Scraped %s: found %d PDF links", url, len(found))
    return found


def _download_pdf(url: str, dest: Path, session: requests.Session) -> bool:
    """Download a PDF to dest. Returns True on success."""
    try:
        resp = session.get(url, headers=_BROWSER_HEADERS, timeout=60, stream=True)
    except Exception as exc:
        logger.warning("Download failed for %s: %s", url, exc)
        return False
    if resp.status_code != 200:
        logger.warning("Download %s returned status %d", url, resp.status_code)
        return False
    # Sanity check the response is actually a PDF, not an HTML error page.
    head = resp.content[:8] if not resp.raw.tell() else b""
    # requests with stream=True needs a different read; re-fetch non-streaming
    # for the actual write because PDFs are small (<2MB typical).
    resp = session.get(url, headers=_BROWSER_HEADERS, timeout=60)
    if not resp.content.startswith(b"%PDF-"):
        logger.warning(
            "Download %s did not return a PDF (got %r…) — skipping",
            url, resp.content[:60],
        )
        return False
    dest.write_bytes(resp.content)
    logger.info("Downloaded %s → %s (%d bytes)", url, dest.name, len(resp.content))
    return True


def _existing_basenames(raw_dir: Path) -> set[str]:
    """Lowercased basenames already present in the ingest dir."""
    return {p.name.lower() for p in raw_dir.iterdir() if p.suffix.lower() == ".pdf"}


async def _record_seen_urls(
    dsn: str, urls_with_source: Iterable[tuple[str, str]],
) -> None:
    """Mark URLs as seen in nmc_monitor_seen_urls so the admin-facing
    monitor doesn't double-flag them as new.

    Schema requires url, filename, source_page (all NOT NULL); first_seen_at
    has a default of now(). filename is derived via _safe_basename so the
    admin monitor's filename column matches what's on disk.
    """
    conn = await asyncpg.connect(dsn)
    try:
        async with conn.transaction():
            for url, source_page in urls_with_source:
                await conn.execute(
                    "INSERT INTO nmc_monitor_seen_urls "
                    "  (url, filename, source_page) "
                    "VALUES ($1, $2, $3) "
                    "ON CONFLICT (url) DO NOTHING",
                    url, _safe_basename(url), source_page,
                )
    finally:
        await conn.close()


def _run_ingest(source: str, repo_root: Path) -> bool:
    """Trigger the named ingest source. Returns True on exit code 0."""
    cmd = [
        "uv", "run", "python", "-m", "ingest.cli",
        "--source", source, "--fresh",
    ]
    logger.info("Running ingest: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=repo_root / "packages" / "ingest",
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error(
            "Ingest %s failed (exit %d):\nSTDOUT: %s\nSTDERR: %s",
            source, result.returncode, result.stdout[-500:], result.stderr[-500:],
        )
        return False
    # Tail the summary so the journal log shows the chunk delta.
    tail_lines = result.stdout.strip().splitlines()[-10:]
    for line in tail_lines:
        logger.info("ingest/%s: %s", source, line)
    return True


async def main() -> int:
    repo_root = Path("/opt/RegKnots")
    raw_dir = repo_root / "data" / "raw" / "nmc"
    if not raw_dir.is_dir():
        logger.error("raw_dir does not exist: %s", raw_dir)
        return 1

    dsn_raw = os.environ.get("REGKNOTS_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not dsn_raw:
        logger.error("No DATABASE_URL in env")
        return 1
    dsn = dsn_raw.replace("postgresql+asyncpg://", "postgresql://")

    session = requests.Session()
    # Track which landing page each URL was found on so the seen-urls
    # table records provenance (the admin-facing nmc-monitor digest
    # groups by source_page).
    discovered: dict[str, str] = {}   # url → first source_page that found it
    fetch_failures = 0
    for landing in _NMC_LANDING_PAGES:
        page_urls = _scrape_landing(landing, session)
        if not page_urls:
            fetch_failures += 1
        for url in page_urls:
            discovered.setdefault(url, landing)

    if not discovered and fetch_failures == len(_NMC_LANDING_PAGES):
        logger.error("All %d landing pages failed to scrape", fetch_failures)
        return 1

    existing = _existing_basenames(raw_dir)
    logger.info("Found %d existing PDFs on disk, %d discovered URLs", len(existing), len(discovered))

    # New = URL whose basename isn't already on disk
    new_urls: list[tuple[str, str]] = []   # (url, target_filename)
    for url in sorted(discovered.keys()):
        target = _safe_basename(url)
        if target not in existing:
            new_urls.append((url, target))

    if not new_urls:
        logger.info("No new PDFs found — nothing to ingest. Exiting clean.")
        # Still mark URLs as seen so admin monitor stays current.
        await _record_seen_urls(dsn, discovered.items())
        return 0

    logger.info("Downloading %d new PDFs:", len(new_urls))
    downloaded = 0
    for url, target in new_urls:
        dest = raw_dir / target
        if _download_pdf(url, dest, session):
            downloaded += 1

    if downloaded == 0:
        logger.warning("Discovered %d new URLs but downloaded 0 — exiting", len(new_urls))
        return 0

    logger.info("Downloaded %d new PDFs. NOTE: ingest will only pick up files "
                "already declared in packages/ingest/ingest/sources/nmc.py "
                "(_POLICY_FILES, _CHECKLIST_FILES, _DOC_META). New filenames "
                "discovered here that aren't yet declared will sit on disk "
                "until manually added to nmc.py — by design, to keep ingest "
                "deterministic and prevent rogue PDFs from changing the corpus.",
                downloaded)

    # Re-run both nmc_policy and nmc_checklist — they're idempotent w.r.t.
    # already-ingested files (content_hash dedup).
    if not _run_ingest("nmc_policy", repo_root):
        return 2
    if not _run_ingest("nmc_checklist", repo_root):
        return 2

    await _record_seen_urls(dsn, discovered.items())
    logger.info("Refresh complete: %d new PDFs downloaded, ingest re-run.", downloaded)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

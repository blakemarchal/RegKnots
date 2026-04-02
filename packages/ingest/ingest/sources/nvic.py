"""
NVIC (Navigation and Vessel Inspection Circular) source adapter.

NVICs are free official USCG guidance documents that explain how marine
inspectors enforce CFR regulations.  This module handles three phases:

  1. Discovery  — scrape the USCG NVIC index page, collect metadata for
                  every active NVIC (skipping cancelled / superseded entries),
                  write data/raw/nvic/index.json as a cache.
  2. Download   — fetch each PDF to data/raw/nvic/{number}.pdf; idempotent
                  (already-present files are skipped).
  3. Parse      — extract text from each PDF, split on top-level numbered
                  section boundaries (1., 2., 3. …), build one Section per
                  numbered section (or one Section for the whole document
                  when no numbered sections are detected).

Section numbering convention:
  section_number = "NVIC {number} §{n}"    e.g. "NVIC 01-23 §3"
  parent_section_number = "NVIC {number}"  e.g. "NVIC 01-23"

Error handling:
  - A failed download is logged to data/failed/nvic_{number}.json; the rest
    of the batch continues.
  - A PDF that yields 0 sections is logged as a warning and skipped.
  - Neither condition raises — the pipeline always finishes.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pdfplumber
from bs4 import BeautifulSoup

from ingest.models import Section

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SOURCE       = "nvic"
TITLE_NUMBER = 0

_INDEX_URL  = "https://www.dco.uscg.mil/Our-Organization/NVIC/"
_BASE_URL   = "https://www.dco.uscg.mil"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
# Full browser-like headers to avoid WAF 403 on dco.uscg.mil
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection":      "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest":  "document",
    "Sec-Fetch-Mode":  "navigate",
    "Sec-Fetch-Site":  "none",
    "Sec-Fetch-User":  "?1",
    "Cache-Control":   "max-age=0",
}
_REQUEST_DELAY = 1.0   # seconds between PDF downloads
_TIMEOUT       = 45.0  # seconds per request

# Keywords that identify cancelled / superseded entries (case-insensitive)
_CANCEL_KEYWORDS = frozenset({"cancelled", "superseded"})

# Top-level section boundary: "1. HEADING" — 1–2 digit number, period, space(s),
# then at least one non-whitespace character.
# Negative lookahead prevents matching "1.1 Sub-section" (next char must not be
# a digit followed by a period).
_SECTION_START = re.compile(r"^(\d{1,2})\.\s+(?!\d+\.)(\S.{1,})")

# Date patterns tried in order
_DATE_RE_DMY  = re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(\d{4})\b")
_DATE_RE_MDY  = re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\b")
_DATE_RE_SLSH = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")

_MONTH_MAP: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3,  "apr": 4,  "may": 5,  "jun": 6,
    "jul": 7, "aug": 8, "sep": 9,  "oct": 10, "nov": 11, "dec": 12,
    # full names
    "january": 1, "february": 2, "march": 3,     "april": 4,
    "june": 6,    "july": 7,     "august": 8,     "september": 9,
    "october": 10, "november": 11, "december": 12,
}

# Pure page-number lines (digits only, optional trailing ‡)
_PAGE_NUMBER = re.compile(r"^\d+\s*[‡]?\s*$")


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class NvicMeta:
    """Metadata extracted from the NVIC index page for one circular."""
    number:         str   # e.g. "01-23"
    title:          str
    effective_date: date
    pdf_url:        str

    def to_dict(self) -> dict:
        return {
            "number":         self.number,
            "title":          self.title,
            "effective_date": self.effective_date.isoformat(),
            "pdf_url":        self.pdf_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "NvicMeta":
        return cls(
            number         = d["number"],
            title          = d["title"],
            effective_date = date.fromisoformat(d["effective_date"]),
            pdf_url        = d["pdf_url"],
        )


# ── Public API ────────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir:    Path,
    failed_dir: Path,
    console=None,
) -> tuple[int, int]:
    """Discover all active NVICs and download their PDFs.

    Returns:
        (success_count, failure_count) — counts of PDFs present after the
        run (includes previously-downloaded files) vs. failed downloads.
    """
    metas = discover_nvics(raw_dir)
    if not metas:
        if console:
            console.print("  [yellow]No active NVICs discovered — check NVIC index URL[/yellow]")
        return 0, 0

    if console:
        console.print(f"  Discovered [bold]{len(metas)}[/bold] active NVICs")

    success, failures = _download_nvics(metas, raw_dir, failed_dir)
    if console:
        console.print(
            f"  PDFs: [green]{success} ready[/green]"
            + (f", [red]{failures} failed[/red]" if failures else "")
        )
    return success, failures


def discover_nvics(raw_dir: Path) -> list[NvicMeta]:
    """Fetch all active NVICs from the USCG decade-based sub-pages.

    The USCG NVIC index is split across 6 decade pages
    (/Our-Organization/NVIC/Year/{decade}/) each of which shows all NVICs for
    that decade on a single table — no JavaScript pagination required.

    Additionally the main index page is scraped as a supplement so that any
    newly posted NVICs that haven't yet appeared on a decade page are captured.

    Skips any entry whose row text contains 'cancelled' or 'superseded'.
    Only entries with a direct PDF link on dco.uscg.mil are collected.

    Table column layout (0-indexed):
      0 NUMBER   — NVIC identifier e.g. "01-23"
      1 URL      — cell containing the PDF <a> link
      2 SUBJECT  — short title / subject line
      3 DESCRIPTION — longer description (unused for now)
      4 YEAR     — 4-digit year string

    Writes raw_dir/index.json as a discovery cache.
    """
    metas: list[NvicMeta] = []
    seen_numbers: set[str] = set()

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        # ── 1. Fetch main index page ─────────────────────────────────────────
        logger.info("Fetching NVIC main index from %s", _INDEX_URL)
        main_resp = client.get(_INDEX_URL, headers=_BROWSER_HEADERS)
        main_resp.raise_for_status()
        main_soup = BeautifulSoup(main_resp.text, "lxml")

        # ── 2. Collect decade sub-page URLs ──────────────────────────────────
        decade_urls: list[str] = []
        for a in main_soup.find_all("a", href=True):
            href = a["href"]
            if "/NVIC/Year/" in href and href.rstrip("/") != "/Our-Organization/NVIC/Year":
                full = _resolve_url(href)
                if full not in decade_urls:
                    decade_urls.append(full)

        logger.info("Found %d decade sub-pages", len(decade_urls))

        # ── 3. Scrape each decade page ────────────────────────────────────────
        pages_to_scrape = decade_urls + [_INDEX_URL]   # decade pages first, main last
        for url in pages_to_scrape:
            try:
                if url == _INDEX_URL:
                    page_soup = main_soup   # already fetched
                else:
                    resp = client.get(url, headers=_BROWSER_HEADERS)
                    resp.raise_for_status()
                    page_soup = BeautifulSoup(resp.text, "lxml")
                    time.sleep(0.5)  # light rate limiting between page fetches
            except Exception as exc:
                logger.warning("Failed to fetch NVIC page %s: %s", url, exc)
                continue

            _extract_table_nvics(page_soup, metas, seen_numbers, source_url=url)

    if not metas:
        logger.warning(
            "No active NVICs discovered — the USCG page structure "
            "may have changed.  Check %s manually.",
            _INDEX_URL,
        )
    else:
        logger.info("Discovered %d active NVICs across all decade pages", len(metas))

    # Cache to disk
    raw_dir.mkdir(parents=True, exist_ok=True)
    cache_path = raw_dir / "index.json"
    with open(cache_path, "w", encoding="utf-8") as fh:
        json.dump([m.to_dict() for m in metas], fh, indent=2)

    return metas


def _extract_table_nvics(
    soup: BeautifulSoup,
    metas: list[NvicMeta],
    seen_numbers: set[str],
    source_url: str = "",
) -> None:
    """Parse NVICs out of the standard USCG table on a given page soup.

    Modifies *metas* and *seen_numbers* in place.  The expected table header
    is "NUMBER URL SUBJECT DESCRIPTION YEAR"; rows without a PDF link are
    silently skipped.
    """
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue
        header_text = rows[0].get_text(" ", strip=True).upper()
        if "NUMBER" not in header_text and "SUBJECT" not in header_text:
            continue  # not the NVIC table

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) < 2:
                continue

            row_text = " ".join(c.get_text(" ", strip=True) for c in cells)
            if any(kw in row_text.lower() for kw in _CANCEL_KEYWORDS):
                continue  # skip cancelled / superseded

            # PDF link lives in the URL cell (column 1)
            pdf_url = _find_pdf_link_in_tag(cells[1] if len(cells) > 1 else row)
            if not pdf_url:
                # Some rows have the link in any cell — fall back to whole row
                pdf_url = _find_pdf_link_in_tag(row)
            if not pdf_url:
                continue

            # NVIC number from column 0; fall back to URL filename
            nvic_num = _parse_nvic_number(cells[0].get_text(strip=True))
            if not nvic_num:
                nvic_num = _number_from_url(pdf_url)
            if not nvic_num or nvic_num in seen_numbers:
                continue

            # Subject / title from column 2 (preferred) or column 3
            title = ""
            for col_idx in (2, 3, 1):
                if len(cells) > col_idx:
                    candidate = cells[col_idx].get_text(" ", strip=True)
                    # Reject if it looks like a URL or bare filename
                    if candidate and not candidate.startswith("/") and ".pdf" not in candidate.lower():
                        title = candidate
                        break
            title = title or f"NVIC {nvic_num}"

            # Effective date — try multiple sources in priority order:
            #   1. Any cell with a full date string (month + day + year)
            #   2. Bare 4-digit year in the last (YEAR) cell
            #   3. 4-digit year component in the PDF URL path
            eff_date: date | None = None
            for cell in reversed(cells):
                eff_date = _parse_date(cell.get_text(strip=True))
                if eff_date:
                    break
            if not eff_date:
                # Last cell typically contains the year
                yr_m = re.search(r"\b(19|20)\d{2}\b", cells[-1].get_text(strip=True))
                if not yr_m:
                    # Fall back to any cell
                    for cell in reversed(cells):
                        yr_m = re.search(r"\b(19|20)\d{2}\b", cell.get_text(strip=True))
                        if yr_m:
                            break
                if not yr_m:
                    # Try the PDF URL path (e.g. /NVIC/2023/foo.pdf)
                    yr_m = re.search(r"\b(19|20)(\d{2})\b", pdf_url)
                if yr_m:
                    try:
                        eff_date = date(int(yr_m.group(0)), 1, 1)
                    except ValueError:
                        pass
            eff_date = eff_date or date.today()

            metas.append(NvicMeta(nvic_num, title[:300], eff_date, pdf_url))
            seen_numbers.add(nvic_num)
            logger.debug("Discovered NVIC %s from %s", nvic_num, source_url)


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all downloaded NVIC PDFs into Section objects.

    Reads the index.json cache written by discover_nvics(), iterates every
    downloaded PDF, and calls _parse_nvic_pdf() for each.  PDFs that are
    missing or produce 0 sections are logged and skipped — they do not raise.
    """
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"NVIC index cache not found at {cache_path}. "
            "Run discovery first (discover_nvics / discover_and_download)."
        )

    with open(cache_path, encoding="utf-8") as fh:
        metas = [NvicMeta.from_dict(d) for d in json.load(fh)]

    sections: list[Section] = []
    parsed_docs = 0

    for meta in metas:
        pdf_path = raw_dir / f"{meta.number}.pdf"
        if not pdf_path.exists():
            logger.warning("NVIC %s: PDF not found at %s, skipping", meta.number, pdf_path)
            continue

        try:
            secs = _parse_nvic_pdf(pdf_path, meta)
        except Exception as exc:
            logger.warning("NVIC %s: parse error — %s", meta.number, exc)
            continue

        if not secs:
            logger.warning("NVIC %s: parsed 0 sections, skipping", meta.number)
            continue

        sections.extend(secs)
        parsed_docs += 1

    logger.info(
        "NVIC: parsed %d sections from %d/%d documents",
        len(sections), parsed_docs, len(metas),
    )
    return sections


def get_source_date(raw_dir: Path) -> date:
    """Return the most recent effective_date across all cached NVICs.

    Used by the pipeline's update-mode short-circuit check.  Falls back to
    today's date if the index cache is absent or empty.
    """
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        return date.today()
    try:
        with open(cache_path, encoding="utf-8") as fh:
            entries = json.load(fh)
        if not entries:
            return date.today()
        return max(date.fromisoformat(e["effective_date"]) for e in entries)
    except Exception:
        return date.today()


# ── Internal helpers ──────────────────────────────────────────────────────────

def _download_nvics(
    metas:      list[NvicMeta],
    raw_dir:    Path,
    failed_dir: Path,
) -> tuple[int, int]:
    """Download PDFs for every NvicMeta entry.  Idempotent: skips existing files."""
    success  = 0
    failures = 0

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(metas, 1):
            pdf_path = raw_dir / f"{meta.number}.pdf"
            if pdf_path.exists():
                logger.debug("NVIC %s: already present, skipping download", meta.number)
                success += 1
                continue

            try:
                logger.info(
                    "Downloading NVIC %s (%d/%d)…", meta.number, i, len(metas)
                )
                resp = client.get(meta.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                pdf_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("NVIC %s: download failed — %s", meta.number, exc)
                _write_download_failure(meta, exc, failed_dir)

            # Respectful rate limiting between requests
            if i < len(metas):
                time.sleep(_REQUEST_DELAY)

    return success, failures


def _write_download_failure(meta: NvicMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    fail_path = failed_dir / f"nvic_{meta.number}.json"
    payload = {
        "nvic_number": meta.number,
        "title":       meta.title,
        "pdf_url":     meta.pdf_url,
        "error":       str(exc),
    }
    try:
        with open(fail_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)
    except OSError:
        pass  # best-effort


def _parse_nvic_pdf(pdf_path: Path, meta: NvicMeta) -> list[Section]:
    """Extract Section objects from a single NVIC PDF.

    Splits the document on top-level numbered section boundaries (lines
    matching "^\\d{1,2}\\. <text>").  Returns one Section per numbered section,
    or a single Section for the whole document if no boundaries are found.
    """
    # ── Extract lines from all pages ─────────────────────────────────────────
    lines: list[str] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                raw = page.extract_text() or ""
                for ln in raw.splitlines():
                    # Strip null bytes — older scanned PDFs sometimes contain
                    # them; PostgreSQL UTF-8 rejects 0x00 at insert time.
                    stripped = ln.strip().replace("\x00", "")
                    if not stripped:
                        continue
                    # Drop bare page numbers
                    if _PAGE_NUMBER.match(stripped):
                        continue
                    lines.append(stripped)
    except Exception as exc:
        logger.warning("NVIC %s: pdfplumber error — %s", meta.number, exc)
        return []

    if not lines:
        logger.warning("NVIC %s: no text extracted from %s", meta.number, pdf_path.name)
        return []

    # ── Split on numbered section boundaries ──────────────────────────────────
    # Each bucket: (section_number_str, heading_text, [content_lines])
    buckets: list[tuple[str, str, list[str]]] = []
    cur_num:  str | None    = None
    cur_head: str           = ""
    cur_body: list[str]     = []

    for ln in lines:
        m = _SECTION_START.match(ln)
        if m:
            n = int(m.group(1))
            # Sanity bounds: real NVIC sections are 1–30; reject higher numbers
            # to avoid false positives from list items or CFR paragraph numbers.
            if 1 <= n <= 30:
                if cur_num is not None:
                    buckets.append((cur_num, cur_head, cur_body))
                cur_num  = m.group(1)
                cur_head = m.group(2).strip()
                cur_body = []
                continue

        if cur_num is not None:
            cur_body.append(ln)

    # Flush last section
    if cur_num is not None:
        buckets.append((cur_num, cur_head, cur_body))

    # ── Fallback: whole document as one section ───────────────────────────────
    if not buckets:
        logger.debug(
            "NVIC %s: no numbered sections detected — storing as single section",
            meta.number,
        )
        return [Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = f"NVIC {meta.number}",
            section_title         = meta.title,
            full_text             = "\n".join(lines),
            up_to_date_as_of      = meta.effective_date,
            parent_section_number = f"NVIC {meta.number}",
        )]

    # ── Build one Section per bucket ──────────────────────────────────────────
    result: list[Section] = []
    for sec_num, heading, body_lines in buckets:
        body = "\n".join(body_lines).strip()
        if not body:
            continue
        sec_title = f"{meta.title} — {heading}" if heading else meta.title
        result.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = f"NVIC {meta.number} \u00a7{sec_num}",
            section_title         = sec_title[:500],
            full_text             = body,
            up_to_date_as_of      = meta.effective_date,
            parent_section_number = f"NVIC {meta.number}",
        ))

    return result


# ── URL / text utilities ──────────────────────────────────────────────────────

def _resolve_url(href: str) -> str:
    """Make a relative or protocol-relative href absolute."""
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return _BASE_URL + href
    return _BASE_URL + "/" + href


def _find_pdf_link_in_tag(tag) -> str | None:
    """Return the first dco.uscg.mil PDF URL found inside *tag*, or None."""
    for a in tag.find_all("a", href=True):
        href = a["href"]
        if href.lower().endswith(".pdf"):
            url = _resolve_url(href)
            if "dco.uscg.mil" in url:
                return url
    return None


def _parse_nvic_number(text: str) -> str | None:
    """Extract a NVIC number like '01-23' or '2-22' from arbitrary text."""
    m = re.search(r"\b(\d{1,2}-\d{2})\b", text)
    return m.group(1) if m else None


def _number_from_url(url: str) -> str | None:
    """Try to extract a NVIC number from a PDF filename."""
    filename = url.rsplit("/", 1)[-1]
    filename = re.sub(r"\.pdf$", "", filename, flags=re.IGNORECASE)
    return _parse_nvic_number(filename)


def _parse_date(text: str) -> date | None:
    """Try to parse a date string.  Returns None if nothing recognisable found."""
    # "15 Jan 2023" / "15 January 2023"
    m = _DATE_RE_DMY.search(text)
    if m:
        day, mon_str, yr = int(m.group(1)), m.group(2).lower()[:3], int(m.group(3))
        mon = _MONTH_MAP.get(mon_str)
        if mon:
            try:
                return date(yr, mon, day)
            except ValueError:
                pass

    # "Jan 15, 2023" / "January 15 2023"
    m = _DATE_RE_MDY.search(text)
    if m:
        mon_str, day, yr = m.group(1).lower()[:3], int(m.group(2)), int(m.group(3))
        mon = _MONTH_MAP.get(mon_str)
        if mon:
            try:
                return date(yr, mon, day)
            except ValueError:
                pass

    # "01/15/2023"
    m = _DATE_RE_SLSH.search(text)
    if m:
        mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return date(yr, mo, day)
        except ValueError:
            pass

    return None

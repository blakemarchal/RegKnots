"""
NVIC (Navigation and Vessel Inspection Circular) source adapter.

NVICs are free official USCG guidance documents that explain how marine
inspectors enforce CFR regulations.  This module handles three phases:

  1. Discovery  — scrape the USCG NVIC index page, collect metadata for
                  every active NVIC (skipping cancelled / superseded entries),
                  write data/raw/nvic/index.json as a cache.
  2. Download   — fetch each PDF to data/raw/nvic/{number}.pdf; idempotent
                  (already-present files are skipped).
  3. Parse      — extract text from each PDF (a scanned PDF with no text
                  layer is read from its OCR text, data/ocr/nvic/{number}.txt)
                  and split it into the circular and its enclosures; see
                  _split_sections.

Section numbering convention (2026-09-27):
  "NVIC 06-72"            the circular's opening (subject, references), or the
                          whole circular when it has no numbered paragraphs
  "NVIC 06-72 §4"         the circular's numbered paragraphs
  "NVIC 06-72 Encl.1"     an enclosure; "NVIC 04-03 Encl.3 §12" when the
                          enclosure's own paragraphs are numbered 1..k
  parent_section_number = "NVIC {number}"  e.g. "NVIC 06-72"

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

from ingest.models import Section, merge_duplicate_sections
from ingest.sources.nvic_fixes import apply_text_fixes

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

# ── Circular and enclosures (2026-09-27) ──────────────────────────────────────
# Numbered lines inside an enclosure restart at 1, so splitting the whole
# document on "N." gave one NVIC several sections with one section_number, and
# chunks with the same (source, section_number, chunk_index) overwrite each
# other on upsert: 3,487 of 6,805 chunks were stored nowhere on 2026-09-27, and
# each weekly --update re-embedded the losers. See _split_sections.

# A running head or title naming an enclosure: "Enclosure (1) to NVIC 6-72",
# "Encl. (2) to NVIC No. 5-93", "Enclosure 1 to COMDTPUB P16700.4" (the NVIC
# series), "Enclosure (1) to NAVIGATION AND VESSEL INSPECTION CIRCULAR 01-18".
# A lone "l" or "I" is a scan's misread 1.
_ENCL_HEAD = re.compile(
    r"^encl(?:osure)?\.?\s*(?:no\.?\s*)?\(?\s*(\d{1,2}|[lI])\s*\)?\s*,?\s+(?:to\s+)?(?:the\s+)?"
    r"(?:nvic|n\.\s*v\.\s*i\.\s*c|navigation\s+and\s+(?:vessel\s+)?inspection\s+circular"
    r"|comdtpub\s+p?\s*16700\.4)",
    re.IGNORECASE,
)
# "ENCLOSURE 1 – REPORTING, …", "Enclosure (1): Underwater Survey …", "ENCLOSURE (2)"
_ENCL_TITLE = re.compile(
    r"^(?:ENCLOSURE|Enclosure)\s*\(?\s*(\d{1,2}|[lI])\s*\)?\s*(?:$|[-–—:]\s*\S)"
)
# The circular's list of its enclosures: "Encl: (1) …", "Enclosures: (1) …" (with a
# colon: "Encl. (2) to NVIC 4-97" is a running head, "enclosure. Ventilation …" text)
_ENCL_LIST = re.compile(r"^encl(?:osure)?s?\.?\s*:", re.IGNORECASE)
# A table-of-contents line: dot leaders, maybe a page number
_TOC_LINE = re.compile(r"(?:\.\s*){4,}\S{0,6}\s*$")
# Running heads sit in a page's first or last lines
_EDGE_LINES = 3
# The page-range label scripts/ocr_scanned_nvics.py writes between OCR batches
_OCR_PAGE_RANGE = re.compile(r"^\[--- pages \d+-\d+ ---\]$")
# The NVIC a section_number belongs to: "NVIC 06-72 Encl.1 §3" -> "NVIC 06-72"
_SECTION_NVIC = re.compile(
    r"^(NVIC \d{1,2}-\d{2}(?: Ch-\d+)?)(?: §\d+| Encl\.\d*(?: §\d+)?)?$"
)
# section_title is cut here; a numbered line that does not fit also stays in the text
_TITLE_MAX = 500


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


# Documents the USCG index does not list, parsed with the NVICs: (meta, PDF file
# name in data/raw/nvic). 2026-09-27 — until now ingested once by a separate script.
# 2026-09-30 — NVIC 04-08 Ch-2 (medical) left this list: the index doesn't list
# it because the Merchant Mariner Medical Manual cancelled it (see RETIRED).
_EXTRA_DOCS: list[tuple[NvicMeta, str]] = []

# NVICs USCG has cancelled that an earlier ingest stored. No parse produces them,
# so prune_scope would keep their rows as "out of scope"; listing them here makes
# a prune (--prune-stale / --prune) remove them. Keys are prune_scope names.
RETIRED: dict[str, str] = {
    "NVIC 04-08 Ch-2": "Cancelled 2019-09-09 by COMDTINST M16721.48, the Merchant Mariner "
                       "Medical Manual (uscg_msm), with NVIC 01-14.",
    "NVIC 09-94": "Marine radar training and certification; marked Cancelled/Superseded "
                  "on the USCG 1990s NVIC page (checked 2026-09-30).",
}


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
            if not pdf_url or "/Portals/" not in pdf_url:
                # Some rows have the link in any cell — fall back to whole row.
                # 2026-09-30: a stored file (/Portals/) anywhere in the row beats
                # a URL-column link outside it (09-00 CH-1's 404s).
                pdf_url = _find_pdf_link_in_tag(row) or pdf_url
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


def parse_source(
    raw_dir: Path, only: list[str] | None = None, ocr_dir: Path | None = None,
) -> list[Section]:
    """Parse all downloaded NVIC PDFs into Section objects.

    Reads the index.json cache written by discover_nvics() plus _EXTRA_DOCS,
    and calls _parse_nvic_pdf() for each PDF. Documents that are missing or
    produce 0 sections are logged and skipped — they do not raise.

    2026-09-27 — a scanned NVIC with OCR text in ocr_dir (default
    data/ocr/nvic, written by scripts/ocr_scanned_nvics.py) is parsed from that
    text instead of its PDF, which has no text layer.

    only: 2026-09-27 — parse just these NVIC numbers (cli --nvic). A number
    that is not listed, or has neither a PDF nor OCR text, raises instead of
    being skipped.
    """
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"NVIC index cache not found at {cache_path}. "
            "Run discovery first (discover_nvics / discover_and_download)."
        )

    with open(cache_path, encoding="utf-8") as fh:
        metas = [NvicMeta.from_dict(d) for d in json.load(fh)]

    ocr_dir = ocr_dir or raw_dir.parent.parent / "ocr" / "nvic"
    docs = [(m, raw_dir / f"{m.number}.pdf") for m in metas]
    docs += [(m, raw_dir / name) for m, name in _EXTRA_DOCS]

    if only is not None:
        docs = [(m, p) for m, p in docs if m.number in only]
        found = {m.number for m, p in docs if p.exists() or (ocr_dir / f"{m.number}.txt").exists()}
        missing = sorted(set(only) - found)
        if missing:
            raise FileNotFoundError(
                f"NVIC {', '.join(missing)}: not in {cache_path}, or no PDF in {raw_dir} "
                f"and no OCR text in {ocr_dir}"
            )

    sections: list[Section] = []
    parsed_docs = 0

    for meta, pdf_path in docs:
        ocr_path = ocr_dir / f"{meta.number}.txt"
        if not pdf_path.exists() and not ocr_path.exists():
            logger.warning("NVIC %s: PDF not found at %s, skipping", meta.number, pdf_path)
            continue

        try:
            if ocr_path.exists():
                secs = _parse_nvic_text(ocr_path.read_text(encoding="utf-8"), meta)
            else:
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
        len(sections), parsed_docs, len(docs),
    )
    return sections


def prune_scope(section_number: str) -> str | None:
    """The NVIC a stored row belongs to ("NVIC 06-72 Encl.1 §3" -> "NVIC 06-72"),
    or None for a name this adapter does not produce.

    2026-09-27 — ingest/prune.py only considers stored rows of NVICs the
    current parse produced, so rows of an NVIC that left the USCG index or
    failed to parse this run are kept.
    """
    m = _SECTION_NVIC.match(section_number or "")
    return m.group(1) if m else None


prune_scope.retired = frozenset(RETIRED)  # read by ingest/prune.py build_report


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
    """Extract Section objects from a single NVIC PDF (see _split_sections)."""
    pages: list[list[str]] = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            for page in pdf.pages:
                pages.append(_clean_lines((page.extract_text() or "").splitlines()))
    except Exception as exc:
        logger.warning("NVIC %s: pdfplumber error — %s", meta.number, exc)
        return []

    lines = [ln for pl in pages for ln in pl]
    if not lines:
        logger.warning("NVIC %s: no text extracted from %s", meta.number, pdf_path.name)
        return []

    # 2026-09-27 — misreads in USCG's retyped text layer (nvic_fixes.py).
    fixed = apply_text_fixes(meta.number, lines)
    if len(fixed) == len(lines):
        rest = iter(fixed)
        return _split_sections([[next(rest) for _ in pl] for pl in pages], meta, paged=True)
    # The fix table keeps line counts (test_nvic_fixes.py); if a fix ever does
    # not, the page edges are lost and enclosures are found by line instead.
    logger.warning("NVIC %s: a text fix changed the line count; finding enclosures by line",
                   meta.number)
    return _split_sections([fixed], meta, paged=False)


def _parse_nvic_text(text: str, meta: NvicMeta) -> list[Section]:
    """Sections from the OCR text of a scanned NVIC (data/ocr/nvic/{number}.txt).

    2026-09-27 — until now ingested by scripts/ingest_ocr_nvics.py with its own
    copy of the old split. The OCR has no page breaks and dropped most running
    heads, so enclosures are found by line.
    """
    lines = apply_text_fixes(meta.number, _clean_lines(text.splitlines()))
    if not any(lines):
        return []
    return _split_sections([lines], meta, paged=False)


def _clean_lines(raw_lines: list[str]) -> list[str]:
    out: list[str] = []
    for ln in raw_lines:
        # Strip null bytes — older scanned PDFs sometimes contain them;
        # PostgreSQL UTF-8 rejects 0x00 at insert time.
        stripped = ln.strip().replace("\x00", "")
        # Drop bare page numbers and the OCR's page-range labels
        if stripped and not _PAGE_NUMBER.match(stripped) and not _OCR_PAGE_RANGE.match(stripped):
            out.append(stripped)
    return out


def _split_sections(pages: list[list[str]], meta: NvicMeta, paged: bool) -> list[Section]:
    """One NVIC's sections (2026-09-27). Every line lands in one section.

      "NVIC 06-72"          the circular's opening (subject, references), or the
                            whole circular when it has no numbered paragraphs
      "NVIC 06-72 §4"       the circular's paragraphs, taken 1, 2, 3… in order;
                            a numbered line out of order (a list item) is text
      "NVIC 06-72 Encl.1"   an enclosure, split into "Encl.1 §1"…"§k" only when
                            its numbered lines run exactly 1..k

    A numbered line with no text of its own keeps its line as its text, and one
    too long for the title stays in the text as well (_paragraph).
    """
    circular, enclosures = _segments(pages, paged)
    base = f"NVIC {meta.number}"
    opening, parts = _number_split(circular, first_any=True)
    out = [_section(meta, base, meta.title, opening)]
    out += [_paragraph(meta, f"{base} §{n}", f"{meta.title} — {head}", head, line, body)
            for n, head, body, line in parts]
    for k, lines in enclosures:
        name, label = (f"{base} Encl.{k}", f"Enclosure ({k})") if k else (f"{base} Encl.", "Enclosure")
        numbers = [s[0] for ln in lines if (s := _numbered(ln))]
        if len(numbers) > 1 and numbers == list(range(1, len(numbers) + 1)):
            opening, parts = _number_split(lines, first_any=False)
        else:
            opening, parts = lines, []
        out.append(_section(meta, name, f"{meta.title} — {label}", opening))
        out += [_paragraph(meta, f"{name} §{n}", f"{meta.title} — {label}: {head}", head, line, body)
                for n, head, body, line in parts]
    # the names are unique by construction; merging is a safety net that warns
    return merge_duplicate_sections([s for s in out if s.full_text])


def _segments(pages: list[list[str]], paged: bool) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """(the circular's lines, [(enclosure number, its lines)]); number 0 = unknown.

    Paged (pdfplumber): the enclosures start at the first page whose first or
    last lines name the lowest enclosure number (earlier marks are the
    circular's own list of enclosures); with no running heads, at the page
    after the circular's "Encl:" list. Unpaged (OCR text): at the first line
    naming the lowest number. A page naming an enclosure already seen (a CH-1
    replacement page filed at the end) joins that enclosure.
    """
    if paged:
        units = pages
        marks = [next((m for ln in pl[:_EDGE_LINES] + pl[-_EDGE_LINES:]
                       if (m := _encl_marker(ln)) is not None), None) for pl in pages]
    else:
        units = [[ln] for ln in pages[0]]
        marks = [_encl_marker(ln) for ln in pages[0]]
    named = [m for m in marks if m is not None]
    # One enclosure number from the first page with text on is the whole PDF's
    # running head (NVIC 2-88 and 4-97 carry it on the circular's own pages),
    # not an enclosure that follows the circular.
    first_text = next((i for i, u in enumerate(units) if u), None)
    if named and len(set(named)) == 1 and marks[first_text] is not None:
        named = []
    if named:
        first = marks.index(min(named))
    else:
        listed = next((i for i, pl in enumerate(pages) if any(_ENCL_LIST.match(ln) for ln in pl)),
                      None) if paged else None
        if listed is None or not any(pages[listed + 1:]):
            return [ln for u in units for ln in u], []
        first = listed + 1
        marks = [None] * len(pages)
        marks[first] = 0
    enclosures: dict[int, list[str]] = {}
    current = marks[first]
    for unit, mark in zip(units[first:], marks[first:]):
        if mark is not None:
            current = mark
        enclosures.setdefault(current, []).extend(unit)
    return [ln for u in units[:first] for ln in u], list(enclosures.items())


def _encl_marker(line: str) -> int | None:
    """The enclosure a running head or title line names: "Enclosure (1) to NVIC 6-72" -> 1."""
    if _TOC_LINE.search(line):
        return None
    m = _ENCL_HEAD.match(line) or _ENCL_TITLE.match(line)
    if not m:
        return None
    return (int(m.group(1)) if m.group(1).isdigit() else 1) or None


def _numbered(line: str) -> tuple[int, str] | None:
    """(n, heading) for a line that may open a numbered section, "4. Revisions. It …":
    n in 1..30, not a table-of-contents line, not a list item in lower case."""
    m = _SECTION_START.match(line)
    if not m or not 1 <= int(m.group(1)) <= 30:
        return None
    heading = m.group(2).strip()
    if heading[0].islower() or _TOC_LINE.search(line):
        return None
    return int(m.group(1)), heading


def _number_split(
    lines: list[str], first_any: bool,
) -> tuple[list[str], list[tuple[int, str, list[str], str]]]:
    """(opening lines, [(n, heading, body lines, the numbered line)]), taking
    numbered lines in order: the first (any number if first_any, else 1), then
    only the next. Any other numbered line (a list item, a restart) stays in the text."""
    opening: list[str] = []
    parts: list[tuple[int, str, list[str], str]] = []
    for ln in lines:
        s = _numbered(ln)
        if s and (s[0] == parts[-1][0] + 1 if parts else first_any or s[0] == 1):
            parts.append((s[0], s[1], [], ln))
            continue
        (parts[-1][2] if parts else opening).append(ln)
    return opening, parts


def _paragraph(meta: NvicMeta, number: str, title: str, head: str, line: str,
               body: list[str]) -> Section:
    """A numbered paragraph: its heading is in the title, and a paragraph with no
    text of its own keeps its heading as its text.

    2026-09-28 — a numbered line longer than the title holds stays in the text
    too. OCR text keeps a whole paragraph on one line ("5. DISCUSSION. The Coast
    Guard, ..."), and everything past the title's 500 chars was in no chunk:
    17,606 chars in 59 sections of 24 of the 52 OCR NVICs. PDF text lines fit.
    """
    if len(title) > _TITLE_MAX:
        body = [line] + body
    return _section(meta, number, title, body or [head])


def _section(meta: NvicMeta, number: str, title: str, lines: list[str]) -> Section:
    return Section(
        source                = SOURCE,
        title_number          = TITLE_NUMBER,
        section_number        = number,
        section_title         = title[:_TITLE_MAX],
        full_text             = "\n".join(lines).strip(),
        up_to_date_as_of      = meta.effective_date,
        parent_section_number = f"NVIC {meta.number}",
    )


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
    """Return the first dco.uscg.mil PDF URL found inside *tag*, or None.

    2026-09-30 — USCG serves most 2014+ NVICs as "….pdf?ver=…", and the
    credentialing ones from an MMC folder whose path has raw spaces. The check
    used to be href.endswith(".pdf"), which skipped every one of them: 36 current
    circulars, including 03-16 (towing officers) and the STCW endorsement series.

    A link under /Portals/ (where USCG stores the files) wins over the others:
    the 09-00 CH-1 row also carries "/NVIC%2009-00,Change%201.pdf", which 404s.
    """
    urls = []
    for a in tag.find_all("a", href=True):
        href = a["href"].strip()
        if href.split("?", 1)[0].split("#", 1)[0].lower().endswith(".pdf"):
            url = _resolve_url(href).replace(" ", "%20")
            if "dco.uscg.mil" in url:
                urls.append(url)
    return next((u for u in urls if "/Portals/" in u), urls[0] if urls else None)


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

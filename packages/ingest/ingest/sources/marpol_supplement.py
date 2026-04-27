"""
MARPOL supplement adapter.

Sprint D6.11 — parses the IMO MARPOL supplements (errata + amendment
delta packs) shipped between consolidated editions. Each supplement is
a small PDF containing one or more MEPC resolutions that amend MARPOL
Annexes; we split by `Resolution MEPC.NNN(YY)` heading and emit each
resolution as its own Section.

Input layout — data/raw/marpol/supplements/<file>.pdf
  Multiple PDFs are processed in one call (mirrors the uscg_msm
  multi-PDF adapter dispatch). Order doesn't matter — each resolution
  has a unique MEPC.NNN(YY) identifier.

Section number canonical form:
  "MARPOL MEPC.384(81)"     parent = "MARPOL Supplements"
  "MARPOL ERRATA 2023-12"   for the December 2023 errata, which has no
                             MEPC resolution number — keyed off the
                             month/year stamp instead.

Uses pdfplumber for text extraction. The IMO eBook PDFs include a
"Delivered by Base to: Blake Marchal" footer plus an order number,
which we strip.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "marpol_supplement"
TITLE_NUMBER = 0

# Latest supplement covered: 5QF520E March 2026. Bump when a newer
# supplement is added to the directory.
SOURCE_DATE = date(2026, 3, 1)

# ── Resolution heading detection ─────────────────────────────────────────────
# Format observed in MARPOL supplements:
#   Resolution MEPC.384(81)
#   adopted on 22 March 2024
# Captures the resolution identifier (e.g., "MEPC.384(81)").
#
# Case-sensitive: lowercase "resolution MEPC.NNN(YY)" appearing in the
# preamble paragraph ("…were adopted by … session by resolution MEPC…")
# is a body reference, not a heading. The actual heading is always
# capitalised "Resolution".
#
# Same-MEPC-code dedup is handled at the call site — IMO supplements
# repeat the resolution number as a running header on every PDF page of
# a multi-page resolution body. We treat only the first occurrence of
# each distinct MEPC code as a true section start.
_RESOLUTION_RE = re.compile(
    r"(?:^|\n)\s*Resolution\s+(MEPC\.\d+\(\d+\))",
)

# Errata/December 2023 doesn't carry a resolution number — it's a
# direct correction. Detect the explicit "Erratum" header so we can
# package it as a single section.
_ERRATUM_HEADER_RE = re.compile(
    r"(?:^|\n)\s*Erratum\s*\n\s*([A-Za-z]+\s+\d{4})",
    re.IGNORECASE,
)


# ── Text cleaning ────────────────────────────────────────────────────────────

# IMO eBook delivery footers — strip these, they're per-purchase metadata.
_DELIVERY_LINE = re.compile(
    r"^.*(?:Delivered by Base to:|Blake Marchal|IP:|On:\s*Mon|On:\s*Tue|On:\s*Wed|On:\s*Thu|On:\s*Fri|On:\s*Sat|On:\s*Sun).*$",
    re.MULTILINE,
)
_COPYRIGHT_LINE = re.compile(
    r"^.*Copyright\s*©.*International\s+Maritime\s+Organization.*$",
    re.MULTILINE | re.IGNORECASE,
)
_ORDER_NUMBER_LINE = re.compile(
    r"^\s*(?:[A-Z0-9]{5,10}|[A-Z]{1,3}:[A-Z]\s*[A-Z]?)\s*$",
    re.MULTILINE,
)
_DASH_LINE = re.compile(r"^[\-–—]{4,}\s*$", re.MULTILINE)
_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)


def _clean_text(text: str) -> str:
    """Strip IMO eBook artefacts."""
    text = text.replace("\x00", "")
    text = _DELIVERY_LINE.sub("", text)
    text = _COPYRIGHT_LINE.sub("", text)
    text = _ORDER_NUMBER_LINE.sub("", text)
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _DASH_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── PDF reading ──────────────────────────────────────────────────────────────

def _extract_pdf_text(pdf_path: Path) -> str:
    """Concatenate all pages of `pdf_path`, separated by blank lines."""
    out_pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                out_pages.append(page_text)
    return "\n\n".join(out_pages)


def _file_descriptor_from_name(pdf_name: str) -> str:
    """Return a short identifier for an erratum/supplement keyed by file name.

    The errata file (no MEPC resolution) needs SOMETHING to key on.
    We pull the month/year from the filename, e.g.
    "QF520E_errata_December2023_PQ.pdf" → "ERRATA 2023-12".
    """
    m = re.search(
        r"(errata|supplement)_(January|February|March|April|May|June|July|August|September|October|November|December)(\d{4})",
        pdf_name,
        re.IGNORECASE,
    )
    if not m:
        return f"SUPPLEMENT {pdf_name}"
    kind, month, year = m.group(1).upper(), m.group(2), m.group(3)
    month_num = {
        "January": "01", "February": "02", "March": "03", "April": "04",
        "May": "05", "June": "06", "July": "07", "August": "08",
        "September": "09", "October": "10", "November": "11", "December": "12",
    }[month]
    return f"{kind} {year}-{month_num}"


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir: Path, failed_dir: Path, console,
) -> tuple[int, int]:
    """No-op discovery — supplements are manually placed by Blake.

    The multi-PDF dispatch path in cli.py calls this before parse_source.
    For NVIC it fetches live; we just report the count of *.pdf files
    already on disk so the CLI summary is honest.
    """
    if not raw_dir.exists():
        return (0, 1)
    found = sum(1 for _ in raw_dir.glob("*.pdf"))
    if console:
        console.print(f"  [cyan]MARPOL supplements:[/cyan] {found} PDF(s) found")
    return (found, 0)


def get_source_date(raw_dir: Path) -> date:
    """Return the source date used on every Section emitted in this run."""
    return SOURCE_DATE


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all MARPOL supplement PDFs and return Section objects.

    `raw_dir` is the supplements directory (data/raw/marpol/supplements).
    Each PDF is read, cleaned, then split by Resolution heading. The
    pre-resolution preamble (cover page metadata, summary table) is
    discarded — it duplicates information already inside each
    resolution body.
    """
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"supplements dir not found: {raw_dir}")

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDFs found in {raw_dir}")

    sections: list[Section] = []
    for pdf_path in pdfs:
        raw = _extract_pdf_text(pdf_path)
        if not raw.strip():
            logger.warning("marpol_supplement: %s extracted no text", pdf_path.name)
            continue

        text = _clean_text(raw)
        descriptor = _file_descriptor_from_name(pdf_path.name)

        # Find every resolution heading position, then dedupe by MEPC
        # code: keep only the FIRST occurrence of each distinct
        # resolution. Subsequent occurrences are page-header repetitions
        # the IMO supplement layout puts at the top of every page of a
        # multi-page resolution body.
        all_matches = list(_RESOLUTION_RE.finditer(text))
        seen: set[str] = set()
        matches = []
        for m in all_matches:
            res_id = m.group(1)
            if res_id in seen:
                continue
            seen.add(res_id)
            matches.append(m)

        if not matches:
            # No MEPC.NNN(YY) headings — likely the December 2023 errata.
            # Emit the whole file as one section.
            erratum_match = _ERRATUM_HEADER_RE.search(text)
            section_number = f"MARPOL {descriptor}"
            section_title = (
                f"MARPOL Erratum — {erratum_match.group(1).strip()}"
                if erratum_match
                else f"MARPOL Supplement — {pdf_path.stem}"
            )
            sections.append(Section(
                source                = SOURCE,
                title_number          = TITLE_NUMBER,
                section_number        = section_number,
                section_title         = section_title[:500],
                full_text             = text,
                up_to_date_as_of      = SOURCE_DATE,
                parent_section_number = "MARPOL Supplements",
            ))
            logger.info("marpol_supplement: %s → 1 section (no MEPC resolution)", pdf_path.name)
            continue

        # Split the text at each resolution boundary.
        for i, m in enumerate(matches):
            res_id = m.group(1)
            start = m.start()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            body = text[start:end].strip()
            if not body:
                continue

            section_number = f"MARPOL {res_id}"
            # Title: first non-empty line after the resolution header.
            title_lines = [
                ln.strip() for ln in body.splitlines()[1:6]
                if ln.strip() and not ln.strip().lower().startswith("adopted on")
            ]
            short_title = title_lines[0] if title_lines else f"Resolution {res_id}"
            section_title = f"MARPOL {res_id} — {short_title}"[:500]

            sections.append(Section(
                source                = SOURCE,
                title_number          = TITLE_NUMBER,
                section_number        = section_number,
                section_title         = section_title,
                full_text             = body,
                up_to_date_as_of      = SOURCE_DATE,
                parent_section_number = "MARPOL Supplements",
            ))
        logger.info(
            "marpol_supplement: %s → %d resolutions",
            pdf_path.name, len(matches),
        )

    logger.info("marpol_supplement: %d total section(s) across %d PDF(s)",
                len(sections), len(pdfs))
    return sections

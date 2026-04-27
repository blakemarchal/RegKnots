"""
IMDG Code supplement adapter.

Sprint D6.12b — parses IMDG errata + supplement PDFs published between
consolidated editions. Currently covers the December 2025 erratum
(corrections to Amendment 42-24, adopted by MSC.556(108)).

Unlike MARPOL supplements which use MEPC.NNN(YY) resolution headings
to delimit sections, IMDG errata are flat correction documents
without resolution numbers — they list corrections by Volume / Part /
Chapter / paragraph. We therefore emit ONE Section per PDF, keying on
the filename's month/year for the section_number. The shared chunker
splits the body into appropriately-sized retrieval chunks.

Input layout — data/raw/imdg/supplements/<file>.pdf
  Multi-PDF directory; the adapter reads every *.pdf in the folder.

Section number canonical form:
  "IMDG Errata 2025-12"     — December 2025 errata (current)
  "IMDG Supplement 2026-XX" — placeholder for future supplements

Parent section: "IMDG"
"""
from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "imdg_supplement"
TITLE_NUMBER = 0

# Source date — bump when a newer supplement lands in the directory.
# Matches the latest supplement currently shipped.
SOURCE_DATE = date(2025, 12, 1)


# ── Filename → section identifier ────────────────────────────────────────────
# Examples:
#   QO200E_errata_December2025_EBK.pdf      → ('errata', 2025, 12)
#   QQQF520E_supplement_August2025_EBK.pdf  → ('supplement', 2025, 08)
_FILENAME_RE = re.compile(
    r"(errata|supplement|corrigenda)_?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"(\d{4})",
    re.IGNORECASE,
)
_MONTH_TO_NUM = {
    "january": "01", "february": "02", "march": "03", "april": "04",
    "may": "05", "june": "06", "july": "07", "august": "08",
    "september": "09", "october": "10", "november": "11", "december": "12",
}


def _file_descriptor(pdf_name: str) -> tuple[str, str]:
    """Return (section_number, section_title_prefix) for a supplement PDF."""
    m = _FILENAME_RE.search(pdf_name)
    if not m:
        # Fallback for unexpected names — use the whole stem.
        stem = pdf_name.rsplit(".", 1)[0]
        return f"IMDG Supplement {stem}", f"IMDG Supplement — {stem}"
    kind = m.group(1).capitalize()
    month_num = _MONTH_TO_NUM[m.group(2).lower()]
    year = m.group(3)
    section_number = f"IMDG {kind} {year}-{month_num}"
    title_prefix = f"IMDG {kind} {m.group(2)} {year}"
    return section_number, title_prefix


# ── Text cleaning ────────────────────────────────────────────────────────────

# IMO eBook delivery footers and copyright lines.
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
    out_pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text.strip():
                out_pages.append(page_text)
    return "\n\n".join(out_pages)


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir: Path, failed_dir: Path, console,
) -> tuple[int, int]:
    """No-op discovery — supplements are manually placed by Blake."""
    if not raw_dir.exists():
        return (0, 1)
    found = sum(1 for _ in raw_dir.glob("*.pdf"))
    if console:
        console.print(f"  [cyan]IMDG supplements:[/cyan] {found} PDF(s) found")
    return (found, 0)


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


def parse_source(raw_dir: Path) -> list[Section]:
    """One Section per supplement PDF. Section number derives from filename."""
    if not raw_dir.is_dir():
        raise FileNotFoundError(f"supplements dir not found: {raw_dir}")

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        raise ValueError(f"No PDFs found in {raw_dir}")

    sections: list[Section] = []
    for pdf_path in pdfs:
        raw = _extract_pdf_text(pdf_path)
        if not raw.strip():
            logger.warning("imdg_supplement: %s extracted no text", pdf_path.name)
            continue

        text = _clean_text(raw)
        section_number, title_prefix = _file_descriptor(pdf_path.name)

        # Look at the first content line for a more descriptive title
        # — IMDG errata tend to start with "Errata and corrigenda" or
        # similar. We append the originating amendment ID if present.
        first_chunk = text[:600].lower()
        suffix = ""
        if "amendment" in first_chunk:
            am_match = re.search(r"amendment\s+(\d+-\d+)", first_chunk)
            if am_match:
                suffix = f" — Amendment {am_match.group(1)}"

        section_title = f"{title_prefix}{suffix}"[:500]

        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = section_number,
            section_title         = section_title,
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = "IMDG",
        ))
        logger.info(
            "imdg_supplement: %s → %s (%d chars)",
            pdf_path.name, section_number, len(text),
        )

    logger.info("imdg_supplement: %d section(s) across %d PDF(s)", len(sections), len(pdfs))
    return sections

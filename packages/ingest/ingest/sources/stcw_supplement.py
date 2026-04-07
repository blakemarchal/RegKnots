"""
STCW January 2025 Supplement adapter.

Parses the supplement PDF containing MSC resolutions that amend STCW 2017.
Each resolution becomes one Section object for the ingest pipeline.

Uses pdfplumber to extract text, then splits by resolution headings.
Mirrors the solas_supplement adapter pattern.
"""

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "stcw_supplement"
TITLE_NUMBER = 0
SOURCE_DATE = date(2025, 1, 1)

# Pattern to match resolution headings like "RESOLUTION MSC.540(107)"
_RESOLUTION_RE = re.compile(
    r"(?:^|\n)\s*(RESOLUTION\s+MSC\.\d+\(\d+\))",
    re.IGNORECASE,
)

# Known resolutions and their chapter mappings for the January 2025 supplement.
# MSC.540(107) and MSC.541(107) cover electronic certificates.
_RESOLUTION_CHAPTERS: dict[str, str] = {
    "MSC.540(107)": "Convention Chapter I — Definitions and Certificates",
    "MSC.541(107)": "STCW Code Part A — Certificates and Endorsements",
}


# ── Text cleaning ─────────────────────────────────────────────────────────────

# Placeholders left by PDF-to-text converters
_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)

# Repeated dashes used as visual separators
_DASH_LINE = re.compile(r"^[\-\u2013\u2014]{4,}\s*$", re.MULTILINE)

# IMO eBook delivery watermark lines
_WATERMARK_LINE = re.compile(
    r"^.*(?:Delivered by|Base to:).*$", re.MULTILINE,
)

# Order/license number lines (short alphanumeric strings like "QQQQD938E", "IP:J A")
_ORDER_NUMBER_LINE = re.compile(
    r"^\s*(?:[A-Z0-9]{5,10}|[A-Z]{1,3}:[A-Z]\s*[A-Z]?)\s*$", re.MULTILINE,
)


def _clean_text(text: str) -> str:
    """Remove PDF and IMO eBook artefacts from supplement text.

    Operations (in order):
      1. Strip null bytes (PostgreSQL rejects U+0000).
      2. Remove lines containing IMO eBook delivery watermarks.
      3. Remove lines that look like order/license numbers.
      4. Remove [IMAGE ...] / [FIGURE ...] placeholders.
      5. Remove pure separator lines (-----).
      6. Collapse runs of 3+ blank lines to 2.
      7. Strip leading/trailing whitespace.
    """
    text = text.replace("\x00", "")
    text = _WATERMARK_LINE.sub("", text)
    text = _ORDER_NUMBER_LINE.sub("", text)
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _DASH_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def parse_source(pdf_path: Path) -> list[Section]:
    """Parse the STCW supplement PDF and return Section objects.

    Args:
        pdf_path: Path to the supplement PDF file.

    Returns:
        List of Section objects, one per resolution plus a preamble.
    """
    import pdfplumber

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Extract full text from all pages
    pages_text: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages_text.append(text)

    full_text = "\n".join(pages_text)

    sections: list[Section] = []

    # ── Preamble: first page summary table ──────────────────────────────────
    preamble_text = _clean_text(pages_text[0]) if pages_text else ""
    if preamble_text:
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number="STCW Supplement Jan2025 Preamble",
            section_title="January 2025 Supplement: Resolution Summary Table",
            full_text=preamble_text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number="STCW 2017 Supplements",
        ))

    # ── Split by resolution headings ────────────────────────────────────────
    matches = list(_RESOLUTION_RE.finditer(full_text))

    if not matches:
        logger.warning("No resolution headings found in STCW supplement PDF")
        return sections

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)

        resolution_text = _clean_text(full_text[start:end])

        # Extract the MSC number from the heading
        msc_match = re.search(r"MSC\.\d+\(\d+\)", heading, re.IGNORECASE)
        msc_number = msc_match.group(0) if msc_match else heading

        chapter_desc = _RESOLUTION_CHAPTERS.get(msc_number, "STCW Amendment")

        section_number = f"STCW Supplement Jan2025 {msc_number}"
        section_title = f"January 2025 Amendment: {chapter_desc} ({msc_number})"

        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=section_number,
            section_title=section_title,
            full_text=resolution_text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number="STCW 2017 Supplements",
        ))

    logger.info(
        "STCW supplement: %d resolutions parsed + preamble",
        len(matches),
    )
    return sections


def dry_run(pdf_path: Path) -> None:
    """Print parsed section titles without embedding or DB writes."""
    sections = parse_source(pdf_path)
    print(f"\nSTCW Supplement: {len(sections)} sections parsed\n")
    for s in sections:
        text_preview = s.full_text[:80].replace("\n", " ")
        print(f"  [{s.section_number}]")
        print(f"    {s.section_title}")
        print(f"    {len(s.full_text):,} chars | {text_preview}...")
        print()

"""
SOLAS January 2026 Supplement adapter.

Parses the supplement PDF containing MSC resolutions that amend SOLAS 2024.
Each resolution becomes one Section object for the ingest pipeline.

Uses pdfplumber to extract text, then splits by resolution headings.
"""

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "solas_supplement"
TITLE_NUMBER = 0
SOURCE_DATE = date(2026, 1, 1)

# Pattern to match resolution headings like "RESOLUTION MSC.520(106)"
_RESOLUTION_RE = re.compile(
    r"(?:^|\n)\s*(RESOLUTION\s+MSC\.\d+\(\d+\))",
    re.IGNORECASE,
)

# Known resolutions and their chapter mappings from the supplement
_RESOLUTION_CHAPTERS: dict[str, str] = {
    "MSC.520(106)": "Chapter II-2 Fire Protection",
    "MSC.522(106)": "Chapter II-1 Construction",
    "MSC.532(107)": "Chapter V Navigation Safety",
    "MSC.533(107)": "Chapter XIV Polar Code",
    "MSC.534(107)": "Chapter II-1 Construction",
    "MSC.550(108)": "Appendix Certificates",
}


def parse_source(pdf_path: Path) -> list[Section]:
    """Parse the SOLAS supplement PDF and return Section objects.

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
    preamble_text = pages_text[0] if pages_text else ""
    if preamble_text.strip():
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number="SOLAS Supplement Jan2026 Preamble",
            section_title="January 2026 Supplement: Resolution Summary Table",
            full_text=preamble_text.strip(),
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number="SOLAS 2024 Supplements",
        ))

    # ── Split by resolution headings ────────────────────────────────────────
    matches = list(_RESOLUTION_RE.finditer(full_text))

    if not matches:
        logger.warning("No resolution headings found in supplement PDF")
        return sections

    for i, match in enumerate(matches):
        heading = match.group(1).strip()
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full_text)

        resolution_text = full_text[start:end].strip()

        # Extract the MSC number from the heading
        msc_match = re.search(r"MSC\.\d+\(\d+\)", heading, re.IGNORECASE)
        msc_number = msc_match.group(0) if msc_match else heading

        chapter_desc = _RESOLUTION_CHAPTERS.get(msc_number, "SOLAS Amendment")

        section_number = f"SOLAS Supplement Jan2026 {msc_number}"
        section_title = f"January 2026 Amendment: {chapter_desc} ({msc_number})"

        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=section_number,
            section_title=section_title,
            full_text=resolution_text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number="SOLAS 2024 Supplements",
        ))

    logger.info(
        "SOLAS supplement: %d resolutions parsed + preamble",
        len(matches),
    )
    return sections


def dry_run(pdf_path: Path) -> None:
    """Print parsed section titles without embedding or DB writes."""
    sections = parse_source(pdf_path)
    print(f"\nSOLAS Supplement: {len(sections)} sections parsed\n")
    for s in sections:
        text_preview = s.full_text[:80].replace("\n", " ")
        print(f"  [{s.section_number}]")
        print(f"    {s.section_title}")
        print(f"    {len(s.full_text):,} chars | {text_preview}...")
        print()

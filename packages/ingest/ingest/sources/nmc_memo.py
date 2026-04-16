"""
NMC memo / policy letter source adapter.

NMC (National Maritime Center) publishes policy letters, memos, and
credentialing guidance as PDFs on dco.uscg.mil/nmc/. These cover:
  - Medical certificate extensions and waiver guidance
  - MMC processing policy changes
  - Endorsement and examination policy updates
  - Credentialing regulation interpretations

This module handles:

  1. Discovery — find all PDFs in data/raw/nmc_memo/
  2. Parse     — extract text from each PDF using pdfplumber, split on
                 numbered section boundaries (same approach as NVICs)
  3. Build     — produce one Section per numbered section (or one per
                 document when no numbered sections are detected)

Section numbering convention:
  section_number = "NMC {filename} §{n}"  e.g. "NMC Policy_Letter_01-24 §3"
  parent_section_number = "NMC {filename}" e.g. "NMC Policy_Letter_01-24"

  When a document has no detectable section boundaries:
  section_number = "NMC {filename}"

Usage:
  1. Download NMC PDFs to data/raw/nmc_memo/
  2. Run: uv run python -m ingest.cli --source nmc_memo --update
"""

import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

SOURCE = "nmc_memo"
TITLE_NUMBER = 0  # Not a CFR title; 0 = non-CFR source

# Attempt to extract a date from the PDF filename or content.
# Default fallback when no date can be extracted.
SOURCE_DATE = date.today()

# Top-level section boundary: "1. HEADING" pattern (same as NVIC adapter)
_SECTION_START = re.compile(r"^(\d{1,2})\.\s+(?!\d+\.)(\S.{1,})")

# Date patterns in filenames like "Policy_Letter_01-24" or "NMC_Memo_2024-03-15"
_FILENAME_DATE_RE = re.compile(r"(\d{4})[-_](\d{2})(?:[-_](\d{2}))?")
_FILENAME_YY_RE = re.compile(r"[-_](\d{2})$")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _extract_date_from_filename(filename: str) -> date:
    """Try to extract a date from the PDF filename. Falls back to today."""
    stem = Path(filename).stem

    # Try YYYY-MM-DD or YYYY_MM_DD
    m = _FILENAME_DATE_RE.search(stem)
    if m:
        try:
            year = int(m.group(1))
            month = int(m.group(2))
            day = int(m.group(3)) if m.group(3) else 1
            return date(year, month, day)
        except ValueError:
            pass

    # Try 2-digit year suffix like "01-24" → 2024
    m2 = _FILENAME_YY_RE.search(stem)
    if m2:
        try:
            yy = int(m2.group(1))
            year = 2000 + yy if yy < 100 else yy
            return date(year, 1, 1)
        except ValueError:
            pass

    return date.today()


def _clean_filename(filename: str) -> str:
    """Convert a PDF filename to a human-readable identifier."""
    stem = Path(filename).stem
    # Replace underscores/hyphens with spaces, strip leading/trailing
    return stem.replace("_", " ").replace("-", " ").strip()


# ── Main entry point ─────────────────────────────────────────────────────────


def parse_source(raw_dir: Path | str) -> list[Section]:
    """Parse all NMC memo PDFs in the given directory into Sections.

    Args:
        raw_dir: Path to data/raw/nmc_memo/ containing PDF files.

    Returns:
        List of Section objects ready for the ingest pipeline.
    """
    raw_dir = Path(raw_dir)
    if not raw_dir.is_dir():
        logger.error("NMC memo directory does not exist: %s", raw_dir)
        return []

    pdfs = sorted(raw_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("No PDF files found in %s", raw_dir)
        return []

    logger.info("Found %d NMC memo PDF(s) in %s", len(pdfs), raw_dir)

    all_sections: list[Section] = []
    for pdf_path in pdfs:
        try:
            sections = _parse_single_pdf(pdf_path)
            all_sections.extend(sections)
            logger.info("Parsed %s: %d section(s)", pdf_path.name, len(sections))
        except Exception:
            logger.exception("Failed to parse NMC memo: %s", pdf_path.name)

    logger.info("Total NMC memo sections: %d from %d PDF(s)", len(all_sections), len(pdfs))
    return all_sections


def _parse_single_pdf(pdf_path: Path) -> list[Section]:
    """Extract text from a single NMC PDF and split into sections."""
    filename = pdf_path.name
    doc_id = _clean_filename(filename)
    doc_date = _extract_date_from_filename(filename)

    # Extract all text
    full_text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text += text + "\n"

    if not full_text.strip():
        logger.warning("No text extracted from %s", filename)
        return []

    # Try to split on numbered section boundaries
    lines = full_text.split("\n")
    section_starts: list[tuple[int, str, str]] = []  # (line_idx, section_num, heading)

    for i, line in enumerate(lines):
        m = _SECTION_START.match(line.strip())
        if m:
            section_starts.append((i, m.group(1), m.group(2).strip()))

    if not section_starts:
        # No numbered sections — treat the entire document as one section
        return [
            Section(
                source=SOURCE,
                title_number=TITLE_NUMBER,
                section_number=f"NMC {doc_id}",
                section_title=doc_id,
                full_text=full_text.strip(),
                up_to_date_as_of=doc_date,
                parent_section_number=None,
            )
        ]

    # Build sections from section boundaries
    sections: list[Section] = []
    parent = f"NMC {doc_id}"

    for idx, (start_line, sec_num, heading) in enumerate(section_starts):
        # Section text runs from this boundary to the next (or end of document)
        end_line = section_starts[idx + 1][0] if idx + 1 < len(section_starts) else len(lines)
        text = "\n".join(lines[start_line:end_line]).strip()

        if not text:
            continue

        sections.append(
            Section(
                source=SOURCE,
                title_number=TITLE_NUMBER,
                section_number=f"NMC {doc_id} §{sec_num}",
                section_title=heading,
                full_text=text,
                up_to_date_as_of=doc_date,
                parent_section_number=parent,
            )
        )

    return sections

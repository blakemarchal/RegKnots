"""COSWP (Code of Safe Working Practices for Merchant Seafarers) adapter.

Sprint D6.97 #54 (2026-05-27) — UK MCA's flagship operational
health-and-safety guidance. 2025 Edition, 544 pages, 34 chapters
plus 4 appendices, glossary, and index. Licensed under the Open
Government Licence v3 — free to redistribute with attribution.

Provided by Captain Karynn Marchal 2026-05-27 as the priority ingest
for the shore-side compliance officer pivot. COSWP is what UK-flag
operators reference for everything from PPE to enclosed-space entry
to hot work to lifting operations.

License: Crown Copyright 2025, Open Government Licence v3.
https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/

Input layout — data/raw/coswp/
  12464_MCA_COSWP_BLACK_AND_WHITE_v3_0W.pdf  (MCA-distributed online edition)

Section numbering: COSWP body uses N.N section headers and N.N.N
paragraph numbering. The parser splits at top-level section
boundaries (N.N) producing sections like:
  "COSWP 2025 Ch.15 §15.1"  — Identifying enclosed spaces
  "COSWP 2025 Ch.15 §15.2"  — Procedures for entry
  "COSWP 2025 Ch.15 §15.3"  — Atmospheric testing
"""

from __future__ import annotations

import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE        = "coswp"
TITLE_NUMBER  = 0
SOURCE_DATE   = date(2026, 5, 27)
# COSWP 2025 Edition published Feb 2025 per PDF metadata.
UP_TO_DATE_AS_OF = date(2025, 2, 26)
PARENT_LABEL  = "COSWP 2025"


CHAPTER_TITLES: dict[int, str] = {
    1:  "Managing occupational health and safety",
    2:  "Safety induction for personnel working on ships",
    3:  "Living on board",
    4:  "Emergency drills and procedures",
    5:  "Fire precautions",
    6:  "Security on board",
    7:  "Workplace health surveillance",
    8:  "Personal protective equipment",
    9:  "Safety signs and their use",
    10: "Manual handling",
    11: "Safe movement on board ship",
    12: "Noise, vibration and other physical agents",
    13: "Safety officials",
    14: "Permit to work systems",
    15: "Entering enclosed spaces",
    16: "Hatch covers and access lids",
    17: "Work at height",
    18: "Provision, care and use of work equipment",
    19: "Lifting equipment and operations",
    20: "Work on machinery and power systems",
    21: "Hazardous substances and mixtures",
    22: "Boarding arrangements",
    23: "Food preparation and handling in the catering department",
    24: "Hot work",
    25: "Painting",
    26: "Anchoring, mooring and towing operations",
    27: "Roll-on/roll-off ferries",
    28: "Dry cargo",
    29: "Tankers and other ships carrying bulk liquid cargoes",
    30: "Port towage industry",
    31: "Ships serving offshore oil and gas installations",
    32: "Ships serving offshore renewables installations",
    33: "Ergonomics",
    34: "Shipyard safety",
}


# Top-level section header: "N.N TitleText" at start of line.
# Examples that should match:
#   "3.6 Avoiding the effects of fatigue (tiredness)"
#   "8.3 Types of equipment"
#   "11.14 Conditions of extreme heat"
#   "19.10 Operational safety measures"
# Examples that should NOT match (these are paragraph numbers):
#   "3.6.1 The International Maritime Organization (IMO) defines..."
#   "15.1.12 The register should record:"
#
# The trailing `(?!\.\d)` lookahead ensures we only catch two-level
# numbering (N.N), not three-level (N.N.N) paragraph references.
_SECTION_HEADER_RE = re.compile(
    r"^[ \t]*(\d{1,2})\.(\d{1,2})(?!\.\d)\s+([A-Z][^\n]{3,200}?)\s*$",
    re.MULTILINE,
)


# ── Public API ───────────────────────────────────────────────────────────────


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    """No-op: COSWP PDF is manually placed in data/raw/coswp/.

    The CLI dispatcher expects this function; returning (file_count, 0)
    lets the dispatcher proceed to parse_source.
    """
    _ = failed_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    count = len(list(raw_dir.glob("*.pdf")))
    console.print(
        f"  [cyan]coswp:[/cyan] {count} COSWP PDF file(s) "
        f"(manually placed, no download)"
    )
    return count, 0


def get_source_date(raw_dir: Path) -> date:
    _ = raw_dir
    return SOURCE_DATE


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse the COSWP PDF into per-section Sections."""
    pdfs = list(raw_dir.glob("*.pdf"))
    if not pdfs:
        logger.warning("coswp: no PDF found in %s", raw_dir)
        return []
    if len(pdfs) > 1:
        logger.warning(
            "coswp: %d PDFs in %s; expected 1. Using first: %s",
            len(pdfs), raw_dir, pdfs[0].name,
        )
    pdf_path = pdfs[0]

    text = _extract_pdf_text(pdf_path)
    if len(text) < 10_000:
        logger.warning(
            "coswp: extracted text suspiciously short (%d chars)", len(text),
        )

    sections = _split_by_section(text)
    logger.info("coswp: parsed %d sections from %s", len(sections), pdf_path.name)
    return sections


# ── PDF text extraction ──────────────────────────────────────────────────────

_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract text from the COSWP PDF, page by page, with normalization
    of repeated whitespace and page-number artifacts."""
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            # Collapse runs of horizontal whitespace
            t = re.sub(r"[ \t]+", " ", t)
            # Collapse runs of blank lines
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


# ── Section splitting ────────────────────────────────────────────────────────


def _split_by_section(text: str) -> list[Section]:
    """Split COSWP text into per-section Sections.

    Algorithm:
      1. Find all `^N.N Title` section headers (MULTILINE).
      2. Slice text between consecutive headers to get section bodies.
      3. Emit one Section per top-level header. Section number is
         "COSWP 2025 Ch.{N} §{N}.{M}" where N=chapter, M=section.
      4. Skip headers whose body is too short (<300 chars) — likely
         a TOC entry or false match.
      5. Validate chapter number against CHAPTER_TITLES; out-of-range
         chapter numbers are skipped to filter false matches inside
         appendices and ranges that don't map to real chapters.
    """
    matches = list(_SECTION_HEADER_RE.finditer(text))
    if not matches:
        logger.warning("coswp: no section headers matched — emitting whole-doc fallback")
        return [_whole_doc_section(text)]

    # Pre-filter: keep only matches whose chapter number is in our
    # known map (1-34). This filters out body-text occurrences of
    # N.N references that aren't section headers, plus appendix
    # numbering (A1.x etc.) which doesn't follow the chapter scheme.
    valid_matches = [
        m for m in matches if int(m.group(1)) in CHAPTER_TITLES
    ]
    if not valid_matches:
        logger.warning("coswp: no in-range section headers found — emitting whole-doc fallback")
        return [_whole_doc_section(text)]

    sections: list[Section] = []
    for i, m in enumerate(valid_matches):
        chapter = int(m.group(1))
        section_num = int(m.group(2))
        title_hint = m.group(3).strip().rstrip(".,;:")
        start = m.start()
        end = valid_matches[i + 1].start() if i + 1 < len(valid_matches) else len(text)
        body = text[start:end].strip()
        if len(body) < 300:
            continue

        section_number = f"{PARENT_LABEL} Ch.{chapter} §{chapter}.{section_num}"
        chapter_title = CHAPTER_TITLES.get(chapter, "")
        section_title = (
            f"{chapter_title} — {title_hint}"
            if chapter_title else title_hint
        )
        # Keep the title length reasonable for display.
        section_title = section_title[:200]

        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=section_number,
            section_title=section_title,
            full_text=body,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number=f"{PARENT_LABEL} Ch.{chapter}",
            published_date=UP_TO_DATE_AS_OF,
        ))

    return sections


def _whole_doc_section(text: str) -> Section:
    """Emergency fallback: emit the whole document as a single Section
    when section-header detection fails. The chunker will handle it.
    Logged at WARNING so we'll see this if the parser regresses."""
    return Section(
        source=SOURCE,
        title_number=TITLE_NUMBER,
        section_number=PARENT_LABEL,
        section_title="Code of Safe Working Practices for Merchant Seafarers (2025)",
        full_text=text,
        up_to_date_as_of=UP_TO_DATE_AS_OF,
        parent_section_number=PARENT_LABEL,
        published_date=UP_TO_DATE_AS_OF,
    )


def dry_run(raw_dir: Path) -> None:
    """Print section-header summary without writing to DB. Useful for
    eyeballing parser behavior after regex changes:
        uv run python -m ingest.sources.coswp --dry-run data/raw/coswp/
    """
    sections = parse_source(raw_dir)
    print(f"\ncoswp: {len(sections)} sections\n")
    for s in sections[:50]:
        print(f"  {s.section_number:40s} {s.section_title[:80]}")
    if len(sections) > 50:
        print(f"  ... and {len(sections) - 50} more")


def _main() -> None:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("raw_dir", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if args.dry_run:
        dry_run(args.raw_dir)
    else:
        print(f"sections={len(parse_source(args.raw_dir))}")


if __name__ == "__main__":
    _main()

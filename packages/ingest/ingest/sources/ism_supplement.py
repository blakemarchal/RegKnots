"""
ISM Code supplementary documents source adapter.

Parses the 6 supplementary documents bundled with the ISM Code in the
IMO e-Publication (2018 consolidated edition):

  1. Resolution A.1118(30) — Implementation Guidelines for Administrations
  2. MSC-MEPC.7/Circ.8    — Operational Implementation for Companies
  3. MSC-MEPC.7/Circ.6    — DPA Qualifications Guidance
  4. MSC-MEPC.7/Circ.7    — Near-miss Reporting Guidance
  5. Resolution MSC.428(98) — Maritime Cyber Risk Management
  6. MSC-FAL.1/Circ.3     — Cyber Risk Management Guidelines

These documents live in the SAME extracted text files as the ISM Code
(data/raw/ism/extracted/).  The ISM Code adapter (ism.py) uses
_find_code_bounds() to scope to Code-only; this adapter takes
everything AFTER the Code ends.

Each supplement becomes a single Section with a unique section_number
(e.g., "ISM Supplement A.1118(30)"), avoiding the numbering collision
that previously caused supplements to overwrite Code sections.

Usage:
  uv run python -m ingest.cli --source ism_supplement --fresh
"""

import logging
import re
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "ism_supplement"
TITLE_NUMBER = 0
SOURCE_DATE = date(2018, 7, 1)  # same publication as ISM Code
UP_TO_DATE_AS_OF = date(2018, 7, 1)

# ── Supplement document boundary markers ────────────────────────────────────
#
# Each supplement starts with a distinctive header line.  These are matched
# in order of appearance in the extracted text (post-Code).

_SUPPLEMENT_DOCS: list[tuple[str, re.Pattern, str]] = [
    # (section_number_suffix, start_regex, human_readable_title)
    (
        "A.1118(30)",
        re.compile(r"^(?:Guidelines\n\n?)?Resolution\s+A\.1118\(30\)", re.MULTILINE),
        "Revised Guidelines on the implementation of the ISM Code by Administrations",
    ),
    (
        "MEPC.7/Circ.8",
        re.compile(r"^MSC-MEPC\.7/Circ\.8", re.MULTILINE),
        "Revised Guidelines for the operational implementation of the ISM Code by Companies",
    ),
    (
        "MEPC.7/Circ.6",
        re.compile(r"^MSC-MEPC\.7/Circ\.6", re.MULTILINE),
        "Guidance on the qualifications, training and experience necessary for the designated person",
    ),
    (
        "MEPC.7/Circ.7",
        re.compile(r"^MSC-MEPC\.7/Circ\.7", re.MULTILINE),
        "Guidance on near-miss reporting",
    ),
    (
        "MSC.428(98)",
        re.compile(r"^Resolution\s+MSC\.428\(98\)", re.MULTILINE),
        "Maritime Cyber Risk Management in Safety Management Systems",
    ),
    (
        "FAL.1/Circ.3",
        re.compile(r"^MSC-FAL\.1/Circ\.3", re.MULTILINE),
        "Guidelines on Maritime Cyber Risk Management",
    ),
]

# ── Code end detection (reuses logic from ism.py) ───────────────────────────

_PART_A_RE = re.compile(r"^PART\s+A\b", re.MULTILINE)
_FIRST_SUPPLEMENT_RE = re.compile(
    r"^(?:Guidelines|Revised Guidelines|Resolution\s+(?:A\.1118|MSC)|MSC-)",
    re.MULTILINE,
)


def _find_supplement_start(text: str) -> int:
    """Return the character position where supplements begin.

    This is the complement of ism.py's _find_code_bounds() — it finds
    the first supplement header after PART A.
    """
    part_a = _PART_A_RE.search(text)
    if not part_a:
        logger.warning("ism_supplement: PART A not found — searching from start")
        search_from = 0
    else:
        search_from = part_a.start()

    for m in _FIRST_SUPPLEMENT_RE.finditer(text):
        if m.start() > search_from:
            return m.start()

    logger.warning("ism_supplement: no supplement headers found")
    return len(text)


# ── Public API ──────────────────────────────────────────────────────────────

def parse_source(raw_dir: Path) -> list[Section]:
    """Parse ISM supplementary documents from extracted text files.

    Args:
        raw_dir: Path to data/raw/ism/extracted/ — same directory as ism.py.
    Returns:
        List of Section objects, one per supplement document.
    """
    txt_files = sorted(
        [f for f in raw_dir.iterdir() if f.suffix == ".txt"],
        key=lambda f: f.name,
    )
    if not txt_files:
        raise ValueError(
            f"No .txt files found in {raw_dir}. "
            "Run ISM --extract first to generate them from page images."
        )

    # Concatenate all pages (same as ism.py)
    full_text = ""
    for txt_path in txt_files:
        page_text = txt_path.read_text(encoding="utf-8", errors="replace")
        full_text += page_text + "\n\n"

    # Take only the supplement portion (everything after Code ends)
    supp_start = _find_supplement_start(full_text)
    supp_text = full_text[supp_start:]

    if not supp_text.strip():
        logger.warning("ism_supplement: no supplement text found")
        return []

    # Find each supplement document's position in the text
    doc_positions: list[tuple[str, str, int]] = []  # (section_suffix, title, position)
    for suffix, pattern, title in _SUPPLEMENT_DOCS:
        m = pattern.search(supp_text)
        if m:
            doc_positions.append((suffix, title, m.start()))
        else:
            logger.warning(
                "ism_supplement: '%s' not found in supplement text", suffix,
            )

    if not doc_positions:
        logger.warning("ism_supplement: no document boundaries found")
        return []

    # Sort by position to get correct document order
    doc_positions.sort(key=lambda x: x[2])

    # Extract text for each supplement document
    sections: list[Section] = []
    for i, (suffix, title, pos) in enumerate(doc_positions):
        # Text runs from this document's start to the next document's start
        end_pos = (
            doc_positions[i + 1][2]
            if i + 1 < len(doc_positions)
            else len(supp_text)
        )
        doc_text = supp_text[pos:end_pos].strip()

        if not doc_text:
            continue

        section_number = f"ISM Supplement {suffix}"
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=section_number,
            section_title=title,
            full_text=doc_text,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number="ISM Code",
        ))

    logger.info(
        "ism_supplement: %d supplement documents parsed from %d text files",
        len(sections), len(txt_files),
    )
    return sections


# ── Dry-run ─────────────────────────────────────────────────────────────────

def dry_run(raw_dir: Path) -> None:
    """Print detected supplement sections and exit."""
    if raw_dir.name != "extracted" and (raw_dir / "extracted").exists():
        extracted_dir = raw_dir / "extracted"
    else:
        extracted_dir = raw_dir

    try:
        sections = parse_source(extracted_dir)
    except ValueError as e:
        import sys
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nISM Supplements: {len(sections)} documents detected\n")
    for s in sections:
        text_preview = s.full_text[:80].replace("\n", " ")
        print(f"  [{s.section_number}]")
        print(f"    Title:  {s.section_title}")
        print(f"    {len(s.full_text):,} chars | {text_preview}...")
        print()

"""
ERG 2024 source adapter.

Parses the 2024 Emergency Response Guidebook (ERG) PDF into Section objects
for the ingest pipeline.  The ERG is a public-domain US/Canadian/Mexican
government publication — NOT copyrighted like SOLAS/COLREGs.

Sections
--------
1. White  — front matter (safety precautions, placards, rail car ID, etc.)
2. Yellow — UN/NA ID → Guide Number index (sorted by ID number)
3. Blue   — Material Name → Guide Number index (sorted alphabetically)
4. Orange — 62 Emergency Response Guide cards (Guides 111-175)
5. Green  — Isolation & Protective Action Distance tables
6. Back   — CBRN agents, glossary, emergency phone numbers

Chunking priority: Orange Guide cards are kept intact (one chunk per guide)
since they are self-contained emergency response cards.
"""

import hashlib
import logging
import re
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "erg"
TITLE_NUMBER = 0
SOURCE_DATE = date(2024, 10, 1)  # ERG 2024 publication date

# ── Orange Guide detection ───────────────────────────────────────────────────

# Flexible pattern: "GUIDE" followed by a 3-digit number (111-175).
# Does NOT require start/end of line — handles pdfplumber putting the title
# on the same line (e.g. "GUIDE 111 MIXED LOAD/UNIDENTIFIED CARGO") as well
# as separate lines ("GUIDE\n111").
_GUIDE_HEADER_RE = re.compile(
    r"GUIDE\s+(\d{3})\b",
)

# Stricter variant for splitting: GUIDE + number near the start of a line.
# Allows optional leading whitespace or "ERG2024" header text.
_GUIDE_SPLIT_RE = re.compile(
    r"(?:^|\n)[^\n]{0,30}?GUIDE\s+(\d{3})\b",
)

# ── Section boundary markers ────────────────────────────────────────────────
# Multiple alternative patterns per section to handle pdfplumber output
# variations (different spacing, column ordering, header formatting).

_YELLOW_MARKERS = [
    re.compile(r"ID\s*No\.?\s+Guide\s*No\.?\s+Name\s+of\s+Material", re.IGNORECASE),
    re.compile(r"UN/NA\s+ID\s+NUMBER\s+INDEX", re.IGNORECASE),
    re.compile(r"ID\s+No\.\s+Guide", re.IGNORECASE),
    # pdfplumber may mangle column headers — fall back to detecting the
    # first line of actual yellow-section data (ID + Guide + Name)
    re.compile(r"^(?:UN|NA)\d{4}\s+\d{3}\s+.{5,}", re.MULTILINE),
]

_BLUE_MARKERS = [
    re.compile(r"Name\s+of\s+Material\s+Guide\s*No\.?\s+ID\s*No\.?", re.IGNORECASE),
    re.compile(r"MATERIAL\s+NAME\s+INDEX", re.IGNORECASE),
    re.compile(r"NAME\s+OF\s+MATERIAL", re.IGNORECASE),
]

_GREEN_MARKERS = [
    re.compile(r"TABLE\s+1\b.*INITIAL\s+ISOLATION", re.IGNORECASE),
    re.compile(r"ISOLATION\s+AND\s+PROTECTIVE\s+ACTION\s+DISTANCES", re.IGNORECASE),
    re.compile(r"TABLE\s+OF\s+INITIAL\s+ISOLATION", re.IGNORECASE),
    re.compile(r"INITIAL\s+ISOLATION\s+AND\s+PROTECTIVE", re.IGNORECASE),
]

_BACK_MARKERS = [
    re.compile(r"CRIMINAL/TERRORIST\s+USE", re.IGNORECASE),
    re.compile(r"IMPROVISED\s+EXPLOSIVE\s+DEVICE", re.IGNORECASE),
    re.compile(r"IED\s+SAFE\s+STANDOFF", re.IGNORECASE),
    re.compile(r"GLOSSARY", re.IGNORECASE),
    re.compile(r"EMERGENCY\s+RESPONSE\s+TELEPHONE\s+NUMBERS", re.IGNORECASE),
]


# ── Public API ───────────────────────────────────────────────────────────────

def parse_source(pdf_path: Path) -> list[Section]:
    """Parse the ERG 2024 PDF and return Section objects.

    Args:
        pdf_path: Path to 'ERG2024-Eng-Web-a.pdf'.

    Returns:
        List of Section objects covering all six ERG sections.
    """
    pages = _extract_pages(pdf_path)
    if not pages:
        raise ValueError(f"No text extracted from {pdf_path}")

    total_chars = sum(len(p) for p in pages)
    non_empty = sum(1 for p in pages if p.strip())
    logger.info(
        "ERG: extracted %d pages (%d non-empty, %d total chars)",
        len(pages), non_empty, total_chars,
    )

    # Log a sample of page content for diagnostics
    for sample_page in (0, 30, 100, 170, 290):
        if sample_page < len(pages):
            snippet = pages[sample_page][:200].replace("\n", "\\n")
            logger.debug("ERG page %d preview: %s", sample_page, snippet)

    # Detect section boundaries by scanning for known header patterns.
    boundaries = _detect_boundaries(pages)

    sections: list[Section] = []

    # Parse each section in priority order
    sections.extend(_parse_orange_guides(pages, boundaries))
    sections.extend(_parse_yellow_section(pages, boundaries))
    sections.extend(_parse_blue_section(pages, boundaries))
    sections.extend(_parse_green_section(pages, boundaries))
    sections.extend(_parse_white_section(pages, boundaries))
    sections.extend(_parse_back_matter(pages, boundaries))

    # Safety net: if section-specific parsing produced nothing, fall back to
    # chunking the entire document in fixed-size blocks so we never return 0.
    if not sections:
        logger.warning(
            "ERG: all section parsers returned 0 sections — "
            "falling back to whole-document chunking"
        )
        full_text = _page_range(pages, 0, len(pages))
        sections = _chunk_text_blocks(full_text, "Full", "ERG 2024", chunk_lines=60)

    logger.info("ERG: %d total sections produced", len(sections))
    return sections


# ── PDF text extraction ──────────────────────────────────────────────────────

def _extract_pages(pdf_path: Path) -> list[str]:
    """Extract text from every page using pdfplumber.

    Per-page errors are caught so one bad page doesn't crash the whole run.
    """
    pages: list[str] = []
    errors = 0
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            try:
                text = page.extract_text() or ""
            except Exception as exc:
                text = ""
                errors += 1
                if errors <= 5:
                    logger.warning("ERG: page %d extraction failed: %s", i, exc)
            pages.append(text)
    if errors:
        logger.warning("ERG: %d/%d pages had extraction errors", errors, len(pages))
    return pages


# ── Section boundary detection ───────────────────────────────────────────────

def _any_marker_match(markers: list[re.Pattern], text: str) -> bool:
    """Return True if any marker regex matches the text."""
    return any(m.search(text) for m in markers)


def _detect_boundaries(pages: list[str]) -> dict[str, int]:
    """Scan pages for section-start markers.  Returns page indices.

    Uses multi-pattern matching with fallback to hardcoded page-fraction
    estimates if regex detection fails.
    """
    boundaries: dict[str, int] = {
        "yellow": -1,
        "blue": -1,
        "orange": -1,
        "green": -1,
        "back": -1,
    }

    n = len(pages)

    for i, text in enumerate(pages):
        if boundaries["yellow"] < 0 and _any_marker_match(_YELLOW_MARKERS, text):
            boundaries["yellow"] = i

        if boundaries["blue"] < 0 and _any_marker_match(_BLUE_MARKERS, text):
            # Only accept blue if it comes after yellow
            if boundaries["yellow"] >= 0 and i > boundaries["yellow"]:
                boundaries["blue"] = i

        if boundaries["orange"] < 0 and _GUIDE_HEADER_RE.search(text):
            guide_match = _GUIDE_HEADER_RE.search(text)
            guide_num = int(guide_match.group(1))
            # Validate it's an actual guide number (111-175) and not a
            # reference in the yellow/blue index
            if 111 <= guide_num <= 175:
                # Must be past the index sections (typically page 140+)
                if i > n * 0.3:
                    boundaries["orange"] = i

        if boundaries["green"] < 0 and _any_marker_match(_GREEN_MARKERS, text):
            if i > n * 0.6:
                boundaries["green"] = i

        if boundaries["back"] < 0 and _any_marker_match(_BACK_MARKERS, text):
            if i > n * 0.8:
                boundaries["back"] = i

    # ── Fallback: hardcoded page-fraction estimates ─────────────────────────
    # The ERG 2024 has ~392 pages with well-known proportions.  If regex
    # detection failed for a boundary, use these as a last resort.
    fallback_fractions = {
        "yellow": 0.07,   # ~page 28 of 392
        "blue":   0.33,   # ~page 131
        "orange": 0.42,   # ~page 166
        "green":  0.73,   # ~page 286
        "back":   0.92,   # ~page 360
    }

    for key, frac in fallback_fractions.items():
        if boundaries[key] < 0:
            fallback_page = int(n * frac)
            logger.warning(
                "ERG: regex detection failed for '%s' boundary — "
                "using fallback page %d (%.0f%% of %d pages)",
                key, fallback_page, frac * 100, n,
            )
            boundaries[key] = fallback_page

    # Enforce monotonic ordering: each boundary must be > previous
    ordered_keys = ["yellow", "blue", "orange", "green", "back"]
    for i_key in range(1, len(ordered_keys)):
        prev = ordered_keys[i_key - 1]
        curr = ordered_keys[i_key]
        if boundaries[curr] <= boundaries[prev]:
            boundaries[curr] = boundaries[prev] + 1

    logger.info("ERG section boundaries (final): %s", boundaries)
    return boundaries


# ── Helpers ──────────────────────────────────────────────────────────────────

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _make_section(
    section_number: str,
    section_title: str,
    full_text: str,
    parent: str | None = None,
) -> Section:
    return Section(
        source=SOURCE,
        title_number=TITLE_NUMBER,
        section_number=section_number,
        section_title=section_title,
        full_text=full_text.strip(),
        up_to_date_as_of=SOURCE_DATE,
        parent_section_number=parent,
    )


def _page_range(pages: list[str], start: int, end: int) -> str:
    """Join page texts for a range [start, end)."""
    return "\n\n".join(pages[start:end])


# ── Orange Guide parsing (highest priority) ─────────────────────────────────

def _parse_orange_guides(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    """Parse the 62 Emergency Response Guide cards (Guides 111-175).

    Each guide is a 2-page spread.  We keep each guide as one chunk.
    """
    start = boundaries["orange"]
    end = boundaries["green"]

    # Collect all text from the orange section
    orange_text = _page_range(pages, start, end)

    if not orange_text.strip():
        logger.warning("ERG: orange section text is empty (pages %d-%d)", start, end)
        return []

    # Find all guide headers in the orange text.  Use the flexible regex and
    # validate the guide number is in the expected range (111-175).
    raw_matches = list(_GUIDE_SPLIT_RE.finditer(orange_text))
    guide_matches = [
        m for m in raw_matches
        if 111 <= int(m.group(1)) <= 175
    ]

    if not guide_matches:
        # Second attempt: even more relaxed — just look for "GUIDE" near a number
        relaxed_re = re.compile(r"GUIDE\s*[:\-]?\s*(\d{3})\b", re.IGNORECASE)
        raw_matches = list(relaxed_re.finditer(orange_text))
        guide_matches = [m for m in raw_matches if 111 <= int(m.group(1)) <= 175]

    if not guide_matches:
        # Third attempt: look for "POTENTIAL HAZARDS" as guide boundaries
        # (every guide card contains this heading)
        hazard_re = re.compile(r"(?:^|\n)\s*POTENTIAL\s+HAZARDS?\b", re.IGNORECASE)
        hazard_matches = list(hazard_re.finditer(orange_text))
        if hazard_matches:
            logger.warning(
                "ERG: found %d 'POTENTIAL HAZARDS' markers but no guide headers — "
                "chunking orange section by hazard markers",
                len(hazard_matches),
            )
            return _chunk_by_markers(
                orange_text, hazard_matches,
                section_prefix="ERG Guide",
                parent="ERG Orange Section — Emergency Response Guides",
            )

        logger.warning("ERG: no guide headers found in orange section — chunking as blocks")
        return _chunk_text_blocks(
            orange_text, "Orange", "Emergency Response Guides", chunk_lines=60,
        )

    # Deduplicate: if the same guide number appears multiple times (e.g. on
    # facing pages), keep only the first occurrence.
    seen_guides: set[str] = set()
    deduped: list[re.Match] = []
    for m in guide_matches:
        gn = m.group(1)
        if gn not in seen_guides:
            seen_guides.add(gn)
            deduped.append(m)
    guide_matches = deduped

    sections: list[Section] = []
    for idx, match in enumerate(guide_matches):
        guide_num = match.group(1)
        chunk_start = match.start()
        chunk_end = (
            guide_matches[idx + 1].start()
            if idx + 1 < len(guide_matches)
            else len(orange_text)
        )

        guide_text = orange_text[chunk_start:chunk_end].strip()
        if not guide_text:
            continue

        # Extract the hazard class title from text after the guide number
        title = _extract_guide_title(guide_text, guide_num)

        sections.append(_make_section(
            section_number=f"ERG Guide {guide_num}",
            section_title=title,
            full_text=guide_text,
            parent="ERG Orange Section — Emergency Response Guides",
        ))

    logger.info("ERG: parsed %d Orange Guide cards", len(sections))
    return sections


def _extract_guide_title(guide_text: str, guide_num: str) -> str:
    """Extract the hazard class title from a guide card's text."""
    # Try multiple patterns for the title line(s) after the guide number
    patterns = [
        # "GUIDE 111\nMIXED LOAD...\nPOTENTIAL HAZARDS"
        re.compile(
            r"GUIDE\s+" + re.escape(guide_num) + r"\b[^\n]*\n\s*(.+?)(?:\n\n|\nPOTENTIAL)",
            re.DOTALL | re.IGNORECASE,
        ),
        # "GUIDE 111 - MIXED LOAD..." (title on same line)
        re.compile(
            r"GUIDE\s+" + re.escape(guide_num) + r"\s*[-–—]\s*(.+?)(?:\n|$)",
            re.IGNORECASE,
        ),
        # "GUIDE 111\nMIXED LOAD" (just grab the next non-empty line)
        re.compile(
            r"GUIDE\s+" + re.escape(guide_num) + r"\b[^\n]*\n\s*([A-Z][^\n]{5,})",
            re.IGNORECASE,
        ),
    ]
    for pattern in patterns:
        m = pattern.search(guide_text)
        if m:
            title = m.group(1).strip()
            # Clean up multi-line titles
            title = re.sub(r"\s*\n\s*", " ", title)
            # Truncate overly long titles
            if len(title) > 120:
                title = title[:117] + "..."
            return title
    return f"Guide {guide_num}"


def _chunk_by_markers(
    text: str,
    markers: list[re.Match],
    section_prefix: str,
    parent: str,
) -> list[Section]:
    """Chunk text by regex match positions as generic boundaries."""
    sections: list[Section] = []
    for idx, match in enumerate(markers):
        chunk_start = match.start()
        chunk_end = markers[idx + 1].start() if idx + 1 < len(markers) else len(text)
        chunk_text = text[chunk_start:chunk_end].strip()
        if chunk_text:
            sections.append(_make_section(
                section_number=f"{section_prefix} {idx + 111}",
                section_title=f"Emergency Response Guide (Card {idx + 1})",
                full_text=chunk_text,
                parent=parent,
            ))
    return sections


# ── Yellow Section (ID Number → Guide lookup) ───────────────────────────────

def _parse_yellow_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries["yellow"]
    end = boundaries["blue"]

    yellow_text = _page_range(pages, start, end)
    if not yellow_text.strip():
        logger.warning("ERG: yellow section text is empty")
        return []
    return _chunk_tabular_by_id(yellow_text, "Yellow", "ID Number Index")


def _chunk_tabular_by_id(full_text: str, color: str, index_label: str) -> list[Section]:
    """Chunk tabular ID/Guide/Name data in groups of ~25-30 entries."""
    # Match lines with UN/NA IDs — try multiple spacing patterns
    entry_patterns = [
        re.compile(r"^((?:UN|NA)\d{4})\s+(\d{3})\s+(.+)$", re.MULTILINE),
        # pdfplumber may use wider spacing or tabs
        re.compile(r"((?:UN|NA)\d{4})\s{2,}(\d{3})\s{2,}(.+?)$", re.MULTILINE),
        # Minimal: just find the ID numbers to anchor chunks
        re.compile(r"((?:UN|NA)\d{4})", re.MULTILINE),
    ]

    entries = None
    for pattern in entry_patterns:
        matches = list(pattern.finditer(full_text))
        if len(matches) >= 10:  # need a reasonable number of entries
            entries = matches
            logger.debug("ERG %s: matched %d entries with pattern %s", color, len(matches), pattern.pattern[:40])
            break

    if not entries:
        # Fallback: chunk by page-sized blocks
        logger.warning("ERG: no tabular entries found in %s section — using text blocks", color)
        return _chunk_text_blocks(full_text, color, index_label, chunk_lines=60)

    sections: list[Section] = []
    group_size = 28

    # For the minimal pattern (only group 1 = ID), handle differently
    has_guide_col = entries[0].lastindex and entries[0].lastindex >= 2

    for i in range(0, len(entries), group_size):
        batch = entries[i : i + group_size]
        first_id = batch[0].group(1)
        last_id = batch[-1].group(1)

        # Extract text span for this batch
        text_start = batch[0].start()
        if i + group_size < len(entries):
            text_end = entries[i + group_size].start()
        else:
            text_end = len(full_text)
        chunk_text = full_text[text_start:text_end].strip()

        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG {color} {first_id}-{last_id}",
                section_title=f"{index_label}: {first_id} to {last_id}",
                full_text=chunk_text,
                parent=f"ERG {color} Section",
            ))

    logger.info("ERG: parsed %d %s section chunks", len(sections), color)
    return sections


# ── Blue Section (Name → Guide lookup) ───────────────────────────────────────

def _parse_blue_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries["blue"]
    end = boundaries["orange"]

    blue_text = _page_range(pages, start, end)
    if not blue_text.strip():
        logger.warning("ERG: blue section text is empty")
        return []

    # Blue section: Name of Material | Guide No. | ID No.
    # Try multiple patterns for different pdfplumber layouts
    entry_patterns = [
        re.compile(r"^(.{10,60}?)\s{2,}(\d{3})\s+((?:UN|NA)\d{4})\s*$", re.MULTILINE),
        re.compile(r"(.{10,60}?)\s{2,}(\d{3})\s{2,}((?:UN|NA)\d{4})", re.MULTILINE),
        # Fall back to finding ID numbers anywhere (anchoring by UN/NA IDs)
        re.compile(r"((?:UN|NA)\d{4})", re.MULTILINE),
    ]

    entries = None
    for pattern in entry_patterns:
        matches = list(pattern.finditer(blue_text))
        if len(matches) >= 10:
            entries = matches
            break

    if not entries:
        logger.warning("ERG: no entries found in Blue section — using text blocks")
        return _chunk_text_blocks(blue_text, "Blue", "Material Name Index", chunk_lines=60)

    sections: list[Section] = []
    group_size = 28
    for i in range(0, len(entries), group_size):
        batch = entries[i : i + group_size]

        # Use ID numbers for section_number if available; otherwise use index
        first_match = batch[0]
        last_match = batch[-1]

        # Try to get an ID-based section name
        if first_match.lastindex and first_match.lastindex >= 3:
            # Full pattern with name + guide + ID
            first_name = first_match.group(1).strip()[:20]
            last_name = last_match.group(1).strip()[:20]
            sec_num = f"ERG Blue {first_name}-{last_name}"
            sec_title = f"Material Name Index: {first_match.group(1).strip()} to {last_match.group(1).strip()}"
        else:
            first_id = first_match.group(1)
            last_id = last_match.group(1)
            sec_num = f"ERG Blue {first_id}-{last_id}"
            sec_title = f"Material Name Index: {first_id} to {last_id}"

        text_start = batch[0].start()
        if i + group_size < len(entries):
            text_end = entries[i + group_size].start()
        else:
            text_end = len(blue_text)
        chunk_text = blue_text[text_start:text_end].strip()

        if chunk_text:
            sections.append(_make_section(
                section_number=sec_num,
                section_title=sec_title,
                full_text=chunk_text,
                parent="ERG Blue Section",
            ))

    logger.info("ERG: parsed %d Blue section chunks", len(sections))
    return sections


# ── Green Section (Isolation & Protection Tables) ────────────────────────────

_TABLE_NUM_RE = re.compile(r"TABLE\s+(\d)", re.IGNORECASE)

def _parse_green_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries["green"]
    end = boundaries["back"]

    green_text = _page_range(pages, start, end)
    if not green_text.strip():
        logger.warning("ERG: green section text is empty")
        return []

    # Try to split into Table 1, Table 2, Table 3
    table_splits = list(_TABLE_NUM_RE.finditer(green_text))

    if len(table_splits) < 2:
        # Couldn't split by table headers — chunk as generic blocks
        return _chunk_text_blocks(
            green_text, "Green", "Isolation & Protective Action Distances",
            chunk_lines=50,
        )

    sections: list[Section] = []

    # Process each table region
    for idx, match in enumerate(table_splits):
        table_num = match.group(1)
        region_start = match.start()
        region_end = (
            table_splits[idx + 1].start()
            if idx + 1 < len(table_splits)
            else len(green_text)
        )
        region_text = green_text[region_start:region_end].strip()

        if table_num == "1":
            sections.extend(_chunk_green_table_by_id(
                region_text, "1",
                "Initial Isolation and Protective Action Distances",
            ))
        elif table_num == "2":
            # Table 2 is typically short — one or two chunks
            sections.append(_make_section(
                section_number="ERG Table 2",
                section_title="Water-Reactive Materials which Produce Toxic Gases",
                full_text=region_text,
                parent="ERG Green Section",
            ))
        elif table_num == "3":
            sections.extend(_chunk_green_table_by_id(
                region_text, "3",
                "Large Spill Protective Action Distances",
            ))

    logger.info("ERG: parsed %d Green section chunks", len(sections))
    return sections


def _chunk_green_table_by_id(
    text: str, table_num: str, title_prefix: str,
) -> list[Section]:
    """Chunk a green table by UN/NA ID entries."""
    entry_re = re.compile(r"((?:UN|NA)\d{4})", re.MULTILINE)
    entries = list(entry_re.finditer(text))

    if not entries:
        return [_make_section(
            section_number=f"ERG Table {table_num}",
            section_title=title_prefix,
            full_text=text,
            parent="ERG Green Section",
        )]

    sections: list[Section] = []
    group_size = 22
    for i in range(0, len(entries), group_size):
        batch = entries[i : i + group_size]
        first_id = batch[0].group(1)
        last_id = batch[-1].group(1)

        text_start = batch[0].start()
        if i + group_size < len(entries):
            text_end = entries[i + group_size].start()
        else:
            text_end = len(text)
        chunk_text = text[text_start:text_end].strip()

        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG Table {table_num} {first_id}-{last_id}",
                section_title=f"{title_prefix}: {first_id} to {last_id}",
                full_text=chunk_text,
                parent="ERG Green Section",
            ))

    return sections


# ── White Section (Front Matter) ─────────────────────────────────────────────

# Known front-matter topics and their detection patterns
_WHITE_TOPICS = [
    ("Safety Precautions", re.compile(r"SAFETY\s+PRECAUTIONS?", re.IGNORECASE)),
    ("Shipping Papers", re.compile(
        r"SHIPPING\s+PAPERS?|HOW\s+TO\s+USE.*SHIPPING", re.IGNORECASE)),
    ("Placard Table", re.compile(
        r"PLACARD|PLACARDS?\s+AND\s+LABELS?", re.IGNORECASE)),
    ("Hazard ID Numbers", re.compile(
        r"HAZARD\s+IDENTIFICATION\s+NUMBER", re.IGNORECASE)),
    ("Rail Car ID Chart", re.compile(r"RAIL\s*CAR|RAILROAD", re.IGNORECASE)),
    ("Road Trailer ID Chart", re.compile(
        r"ROAD\s+TRAILER|HIGHWAY", re.IGNORECASE)),
    ("Pipeline Markings", re.compile(r"PIPELINE", re.IGNORECASE)),
]


def _parse_white_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    end = boundaries["yellow"]

    white_text = _page_range(pages, 0, end)
    if not white_text.strip():
        logger.warning("ERG: white section text is empty")
        return []

    # Try to detect topic boundaries
    topic_spans: list[tuple[str, int, int]] = []
    for topic_name, pattern in _WHITE_TOPICS:
        match = pattern.search(white_text)
        if match:
            topic_spans.append((topic_name, match.start(), -1))

    if not topic_spans:
        # Fallback: chunk by page groups
        return _chunk_text_blocks(
            white_text, "White", "Front Matter", chunk_lines=80,
        )

    # Sort by position and compute spans
    topic_spans.sort(key=lambda x: x[1])
    sections: list[Section] = []
    for idx, (name, start, _) in enumerate(topic_spans):
        end_pos = (
            topic_spans[idx + 1][1]
            if idx + 1 < len(topic_spans)
            else len(white_text)
        )
        chunk_text = white_text[start:end_pos].strip()
        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG {name}",
                section_title=name,
                full_text=chunk_text,
                parent="ERG White Section — Front Matter",
            ))

    # If there's text before the first detected topic (cover page, TOC, etc.)
    if topic_spans and topic_spans[0][1] > 200:
        preamble = white_text[: topic_spans[0][1]].strip()
        if preamble:
            sections.insert(0, _make_section(
                section_number="ERG How to Use This Guidebook",
                section_title="How to Use This Guidebook",
                full_text=preamble,
                parent="ERG White Section — Front Matter",
            ))

    logger.info("ERG: parsed %d White section chunks", len(sections))
    return sections


# ── Back Matter ──────────────────────────────────────────────────────────────

_BACK_TOPICS = [
    ("CBRN Chemical Agents", re.compile(
        r"CRIMINAL/TERRORIST\s+USE|CHEMICAL\s+(?:AGENTS|WEAPONS)", re.IGNORECASE)),
    ("CBRN Biological Agents", re.compile(
        r"BIOLOGICAL\s+(?:AGENTS|WEAPONS)", re.IGNORECASE)),
    ("CBRN Radiological Agents", re.compile(
        r"RADIOLOGICAL\s+(?:AGENTS|WEAPONS)|DIRTY\s+BOMB", re.IGNORECASE)),
    ("IED Safe Standoff Distances", re.compile(
        r"IED|IMPROVISED\s+EXPLOSIVE|SAFE\s+STANDOFF", re.IGNORECASE)),
    ("Glossary", re.compile(r"GLOSSARY", re.IGNORECASE)),
    ("Emergency Phone Numbers", re.compile(
        r"EMERGENCY\s+RESPONSE\s+TELEPHONE|EMERGENCY\s+CONTACTS?", re.IGNORECASE)),
]


def _parse_back_matter(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries["back"]

    back_text = _page_range(pages, start, len(pages))
    if not back_text.strip():
        logger.warning("ERG: back matter text is empty")
        return []

    topic_spans: list[tuple[str, int]] = []
    for topic_name, pattern in _BACK_TOPICS:
        match = pattern.search(back_text)
        if match:
            topic_spans.append((topic_name, match.start()))

    if not topic_spans:
        return _chunk_text_blocks(back_text, "Back", "Back Matter", chunk_lines=80)

    topic_spans.sort(key=lambda x: x[1])
    sections: list[Section] = []
    for idx, (name, span_start) in enumerate(topic_spans):
        end_pos = (
            topic_spans[idx + 1][1]
            if idx + 1 < len(topic_spans)
            else len(back_text)
        )
        chunk_text = back_text[span_start:end_pos].strip()

        # Split glossary into A-L and M-Z if large
        if name == "Glossary" and len(chunk_text) > 3000:
            mid = len(chunk_text) // 2
            # Find a good split point near the middle (at a letter boundary)
            split_match = re.search(
                r"\n[M-Nm-n]", chunk_text[mid - 200 : mid + 200],
            )
            if split_match:
                split_pos = mid - 200 + split_match.start()
                sections.append(_make_section(
                    section_number="ERG Glossary A-L",
                    section_title="Glossary A-L",
                    full_text=chunk_text[:split_pos].strip(),
                    parent="ERG Back Matter",
                ))
                sections.append(_make_section(
                    section_number="ERG Glossary M-Z",
                    section_title="Glossary M-Z",
                    full_text=chunk_text[split_pos:].strip(),
                    parent="ERG Back Matter",
                ))
                continue

        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG {name}",
                section_title=name,
                full_text=chunk_text,
                parent="ERG Back Matter",
            ))

    logger.info("ERG: parsed %d Back Matter chunks", len(sections))
    return sections


# ── Generic text block chunker (fallback) ────────────────────────────────────

def _chunk_text_blocks(
    text: str,
    color: str,
    label: str,
    chunk_lines: int = 60,
) -> list[Section]:
    """Split text into fixed-size line blocks as a fallback chunking strategy."""
    lines = text.split("\n")
    sections: list[Section] = []
    for i in range(0, len(lines), chunk_lines):
        block = "\n".join(lines[i : i + chunk_lines]).strip()
        if not block:
            continue
        chunk_idx = i // chunk_lines + 1
        sections.append(_make_section(
            section_number=f"ERG {color} Block {chunk_idx}",
            section_title=f"{label} (Part {chunk_idx})",
            full_text=block,
            parent=f"ERG {color} Section",
        ))
    return sections

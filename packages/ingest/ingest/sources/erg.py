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

# Matches "GUIDE" on one line followed by a 3-digit guide number (111-175).
# The PDF renders these as large headings; pdfplumber produces them on
# separate lines or with varying whitespace.
_GUIDE_HEADER_RE = re.compile(
    r"^GUIDE\s*\n?\s*(\d{3})\s*$",
    re.MULTILINE,
)

# Matches the hazard class title line(s) immediately after the guide number.
# E.g., "Gases - Flammable (Including Refrigerated Liquids)"
_GUIDE_TITLE_RE = re.compile(
    r"^GUIDE\s*\n?\s*\d{3}\s*\n\s*(.+?)(?:\n\n|\nPOTENTIAL)",
    re.MULTILINE | re.DOTALL,
)

# ── Section boundary markers ────────────────────────────────────────────────

_YELLOW_HEADER_RE = re.compile(
    r"(?:ID\s*No\.?\s+Guide\s*No\.?\s+Name\s+of\s+Material"
    r"|UN/NA\s+ID\s+NUMBER\s+INDEX)",
    re.IGNORECASE,
)

_BLUE_HEADER_RE = re.compile(
    r"(?:Name\s+of\s+Material\s+Guide\s*No\.?\s+ID\s*No\.?"
    r"|MATERIAL\s+NAME\s+INDEX)",
    re.IGNORECASE,
)

_GREEN_HEADER_RE = re.compile(
    r"(?:TABLE\s+1\b.*INITIAL\s+ISOLATION"
    r"|ISOLATION\s+AND\s+PROTECTIVE\s+ACTION\s+DISTANCES"
    r"|TABLE\s+OF\s+INITIAL\s+ISOLATION)",
    re.IGNORECASE,
)

_BACK_MATTER_RE = re.compile(
    r"(?:CRIMINAL/TERRORIST\s+USE"
    r"|IMPROVISED\s+EXPLOSIVE\s+DEVICE"
    r"|IED\s+SAFE\s+STANDOFF"
    r"|GLOSSARY"
    r"|EMERGENCY\s+RESPONSE\s+TELEPHONE\s+NUMBERS)",
    re.IGNORECASE,
)


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

    logger.info("ERG: extracted %d pages of text", len(pages))

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

    logger.info("ERG: %d total sections produced", len(sections))
    return sections


# ── PDF text extraction ──────────────────────────────────────────────────────

def _extract_pages(pdf_path: Path) -> list[str]:
    """Extract text from every page using pdfplumber."""
    pages: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return pages


# ── Section boundary detection ───────────────────────────────────────────────

def _detect_boundaries(pages: list[str]) -> dict[str, int]:
    """Scan pages for section-start markers.  Returns page indices."""
    boundaries: dict[str, int] = {
        "yellow": -1,
        "blue": -1,
        "orange": -1,
        "green": -1,
        "back": -1,
    }

    for i, text in enumerate(pages):
        if boundaries["yellow"] < 0 and _YELLOW_HEADER_RE.search(text):
            boundaries["yellow"] = i
        if boundaries["blue"] < 0 and _BLUE_HEADER_RE.search(text):
            # Only accept blue if it comes after yellow
            if boundaries["yellow"] >= 0 and i > boundaries["yellow"]:
                boundaries["blue"] = i
        if boundaries["orange"] < 0 and _GUIDE_HEADER_RE.search(text):
            # First orange guide page
            if i > boundaries.get("blue", 0) or i > 100:
                boundaries["orange"] = i
        if boundaries["green"] < 0 and _GREEN_HEADER_RE.search(text):
            if i > boundaries.get("orange", 0):
                boundaries["green"] = i
        if boundaries["back"] < 0 and _BACK_MATTER_RE.search(text):
            if boundaries["green"] >= 0 and i > boundaries["green"]:
                boundaries["back"] = i

    # White section is always the beginning (pages 0 to yellow-1)
    logger.info("ERG section boundaries: %s", boundaries)
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
    start = boundaries.get("orange", -1)
    end = boundaries.get("green", len(pages))
    if start < 0:
        logger.warning("ERG: could not detect Orange section start")
        return []
    if end < 0:
        end = len(pages)

    # Collect all text from the orange section
    orange_text = _page_range(pages, start, end)

    # Split into individual guides by the GUIDE NNN header pattern
    guide_splits = list(_GUIDE_HEADER_RE.finditer(orange_text))
    if not guide_splits:
        logger.warning("ERG: no guide headers found in orange section")
        return []

    sections: list[Section] = []
    for idx, match in enumerate(guide_splits):
        guide_num = match.group(1)
        chunk_start = match.start()
        chunk_end = guide_splits[idx + 1].start() if idx + 1 < len(guide_splits) else len(orange_text)

        guide_text = orange_text[chunk_start:chunk_end].strip()

        # Extract the hazard class title (line(s) after the guide number)
        title_match = re.search(
            r"^GUIDE\s*\n?\s*\d{3}\s*\n\s*(.+?)(?:\n\n|\nPOTENTIAL)",
            guide_text,
            re.MULTILINE | re.DOTALL,
        )
        if title_match:
            title = title_match.group(1).strip()
            # Clean up multi-line titles
            title = re.sub(r"\s*\n\s*", " ", title)
        else:
            title = f"Guide {guide_num}"

        sections.append(_make_section(
            section_number=f"ERG Guide {guide_num}",
            section_title=title,
            full_text=guide_text,
            parent="ERG Orange Section — Emergency Response Guides",
        ))

    logger.info("ERG: parsed %d Orange Guide cards", len(sections))
    return sections


# ── Yellow Section (ID Number → Guide lookup) ───────────────────────────────

def _parse_yellow_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries.get("yellow", -1)
    end = boundaries.get("blue", -1)
    if start < 0:
        logger.warning("ERG: could not detect Yellow section")
        return []
    if end < 0:
        end = boundaries.get("orange", len(pages))

    yellow_text = _page_range(pages, start, end)
    return _chunk_tabular_by_id(yellow_text, "Yellow", "ID Number Index")


def _chunk_tabular_by_id(full_text: str, color: str, index_label: str) -> list[Section]:
    """Chunk tabular ID/Guide/Name data in groups of ~25-30 entries."""
    # Match lines that start with UN or NA followed by digits
    entry_re = re.compile(r"^((?:UN|NA)\d{4})\s+(\d{3})\s+(.+)$", re.MULTILINE)
    entries = list(entry_re.finditer(full_text))

    if not entries:
        # Fallback: chunk by page-sized blocks
        return _chunk_text_blocks(full_text, color, index_label, chunk_lines=60)

    sections: list[Section] = []
    group_size = 28
    for i in range(0, len(entries), group_size):
        batch = entries[i : i + group_size]
        first_id = batch[0].group(1)
        last_id = batch[-1].group(1)

        # Extract text span for this batch
        text_start = batch[0].start()
        text_end = batch[-1].end()
        # Include any trailing text until the next entry or end
        if i + group_size < len(entries):
            text_end = entries[i + group_size].start()
        chunk_text = full_text[text_start:text_end].strip()

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
    start = boundaries.get("blue", -1)
    end = boundaries.get("orange", -1)
    if start < 0:
        logger.warning("ERG: could not detect Blue section")
        return []
    if end < 0:
        end = len(pages)

    blue_text = _page_range(pages, start, end)

    # Blue section: Name of Material | Guide No. | ID No.
    entry_re = re.compile(r"^(.{10,60}?)\s{2,}(\d{3})\s+((?:UN|NA)\d{4})\s*$", re.MULTILINE)
    entries = list(entry_re.finditer(blue_text))

    if not entries:
        return _chunk_text_blocks(blue_text, "Blue", "Material Name Index", chunk_lines=60)

    sections: list[Section] = []
    group_size = 28
    for i in range(0, len(entries), group_size):
        batch = entries[i : i + group_size]
        first_name = batch[0].group(1).strip()
        last_name = batch[-1].group(1).strip()

        # Truncate long names for the section_number
        first_short = first_name[:20].strip()
        last_short = last_name[:20].strip()

        text_start = batch[0].start()
        text_end = batch[-1].end()
        if i + group_size < len(entries):
            text_end = entries[i + group_size].start()
        chunk_text = blue_text[text_start:text_end].strip()

        sections.append(_make_section(
            section_number=f"ERG Blue {first_short}-{last_short}",
            section_title=f"Material Name Index: {first_name} to {last_name}",
            full_text=chunk_text,
            parent="ERG Blue Section",
        ))

    logger.info("ERG: parsed %d Blue section chunks", len(sections))
    return sections


# ── Green Section (Isolation & Protection Tables) ────────────────────────────

_TABLE_NUM_RE = re.compile(r"TABLE\s+(\d)", re.IGNORECASE)

def _parse_green_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries.get("green", -1)
    end = boundaries.get("back", -1)
    if start < 0:
        logger.warning("ERG: could not detect Green section")
        return []
    if end < 0:
        end = len(pages)

    green_text = _page_range(pages, start, end)

    # Try to split into Table 1, Table 2, Table 3
    table_splits = list(_TABLE_NUM_RE.finditer(green_text))

    if len(table_splits) < 2:
        # Couldn't split by table headers — chunk as generic blocks
        return _chunk_text_blocks(green_text, "Green", "Isolation & Protective Action Distances", chunk_lines=50)

    sections: list[Section] = []

    # Process each table region
    for idx, match in enumerate(table_splits):
        table_num = match.group(1)
        region_start = match.start()
        region_end = table_splits[idx + 1].start() if idx + 1 < len(table_splits) else len(green_text)
        region_text = green_text[region_start:region_end].strip()

        if table_num == "1":
            sections.extend(_chunk_green_table_by_id(region_text, "1",
                "Initial Isolation and Protective Action Distances"))
        elif table_num == "2":
            # Table 2 is typically short — one or two chunks
            sections.append(_make_section(
                section_number="ERG Table 2",
                section_title="Water-Reactive Materials which Produce Toxic Gases",
                full_text=region_text,
                parent="ERG Green Section",
            ))
        elif table_num == "3":
            sections.extend(_chunk_green_table_by_id(region_text, "3",
                "Large Spill Protective Action Distances"))

    logger.info("ERG: parsed %d Green section chunks", len(sections))
    return sections


def _chunk_green_table_by_id(text: str, table_num: str, title_prefix: str) -> list[Section]:
    """Chunk a green table by UN/NA ID entries."""
    entry_re = re.compile(r"^((?:UN|NA)\d{4})", re.MULTILINE)
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
        text_end = batch[-1].end()
        if i + group_size < len(entries):
            text_end = entries[i + group_size].start()
        else:
            text_end = len(text)
        chunk_text = text[text_start:text_end].strip()

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
    ("Safety Precautions", re.compile(r"SAFETY\s+PRECAUTIONS", re.IGNORECASE)),
    ("Shipping Papers", re.compile(r"SHIPPING\s+PAPERS?|HOW\s+TO\s+USE.*SHIPPING", re.IGNORECASE)),
    ("Placard Table", re.compile(r"PLACARD|PLACARDS?\s+AND\s+LABELS?", re.IGNORECASE)),
    ("Hazard ID Numbers", re.compile(r"HAZARD\s+IDENTIFICATION\s+NUMBER", re.IGNORECASE)),
    ("Rail Car ID Chart", re.compile(r"RAIL\s*CAR|RAILROAD", re.IGNORECASE)),
    ("Road Trailer ID Chart", re.compile(r"ROAD\s+TRAILER|HIGHWAY", re.IGNORECASE)),
    ("Pipeline Markings", re.compile(r"PIPELINE", re.IGNORECASE)),
]


def _parse_white_section(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    end = boundaries.get("yellow", -1)
    if end < 0:
        end = min(28, len(pages))

    white_text = _page_range(pages, 0, end)

    # Try to detect topic boundaries
    topic_spans: list[tuple[str, int, int]] = []
    for topic_name, pattern in _WHITE_TOPICS:
        match = pattern.search(white_text)
        if match:
            topic_spans.append((topic_name, match.start(), -1))

    if not topic_spans:
        # Fallback: chunk by page groups
        return _chunk_text_blocks(white_text, "White", "Front Matter", chunk_lines=80)

    # Sort by position and compute spans
    topic_spans.sort(key=lambda x: x[1])
    sections: list[Section] = []
    for idx, (name, start, _) in enumerate(topic_spans):
        end_pos = topic_spans[idx + 1][1] if idx + 1 < len(topic_spans) else len(white_text)
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
    ("Glossary", re.compile(r"^GLOSSARY", re.IGNORECASE | re.MULTILINE)),
    ("Emergency Phone Numbers", re.compile(
        r"EMERGENCY\s+RESPONSE\s+TELEPHONE|EMERGENCY\s+CONTACTS?", re.IGNORECASE)),
]


def _parse_back_matter(pages: list[str], boundaries: dict[str, int]) -> list[Section]:
    start = boundaries.get("back", -1)
    if start < 0:
        logger.warning("ERG: could not detect Back Matter section")
        return []

    back_text = _page_range(pages, start, len(pages))

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
        end_pos = topic_spans[idx + 1][1] if idx + 1 < len(topic_spans) else len(back_text)
        chunk_text = back_text[span_start:end_pos].strip()

        # Split glossary into A-L and M-Z if large
        if name == "Glossary" and len(chunk_text) > 3000:
            mid = len(chunk_text) // 2
            # Find a good split point near the middle (at a letter boundary)
            split_match = re.search(r"\n[M-Nm-n]", chunk_text[mid - 200 : mid + 200])
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

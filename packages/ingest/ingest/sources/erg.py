"""
ERG 2024 source adapter.

Parses the 2024 Emergency Response Guidebook (ERG) PDF into Section objects
for the ingest pipeline.  The ERG is a public-domain US/Canadian/Mexican
government publication -- NOT copyrighted like SOLAS/COLREGs.

Sections
--------
1. White  -- front matter (safety precautions, placards, rail car ID, etc.)
2. Yellow -- UN/NA ID -> Guide Number index (sorted by ID number)
3. Blue   -- Material Name -> Guide Number index (sorted alphabetically)
4. Orange -- 62 Emergency Response Guide cards (Guides 111-175)
5. Green  -- Isolation & Protective Action Distance tables
6. Back   -- CBRN agents, glossary, emergency phone numbers

Chunking priority: Orange Guide cards are kept intact (one chunk per guide)
since they are self-contained emergency response cards.

Actual pdfplumber output format (from VPS extraction):
  Page 30 (yellow):  "ID Guide Name of Material ID Guide Name of Material\\n
                      No. No. No. No.\\n--- 112 Ammo..."
  Page 100 (blue):   "Name of Material Guide ID Name of Material Guide ID\\n
                      No. No. No. No.\\nCalcium arsenate 151 1573..."
  Page 170 (orange): "GUIDE\\nGases - Toxic - Flammable\\n119\\n
                      EMERGENCY RESPONSE\\nFIRE\\n..."

Key: pdfplumber uses \\n between text elements, NOT double-spaces.  Column
headers like "ID No." are split across lines ("ID" on one, "No." on next).
Guide cards have GUIDE, title, and number each on separate lines.
"""

import hashlib
import logging
import re
import signal
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "erg"
TITLE_NUMBER = 0
SOURCE_DATE = date(2024, 10, 1)  # ERG 2024 publication date

# Per-page extraction timeout in seconds.
_PAGE_TIMEOUT = 10

# -- Orange Guide regexes (newline-separated pdfplumber output) ---------------
#
# Actual format: "GUIDE\n{title}\n{number}\nEMERGENCY RESPONSE\n..."
# or:            "GUIDE\n{title}\n{number}\nPOTENTIAL HAZARDS\n..."

# Finds guide number on its own line followed by POTENTIAL HAZARDS or
# EMERGENCY RESPONSE on the next line.
_GUIDE_NUM_LINE_RE = re.compile(
    r"\n(\d{3})\n(?:POTENTIAL\s+HAZARDS|EMERGENCY\s+RESPONSE)",
)

# Extracts title: line(s) between "GUIDE\n" and "\n{3-digit}\n"
_GUIDE_TITLE_EXTRACT_RE = re.compile(
    r"GUIDE\n(.+?)\n(\d{3})\n",
    re.DOTALL,
)

# For splitting: each guide card page starts with "GUIDE\n" (GUIDE on its
# own line).  Pages are joined by \n\n, so the pattern is \n\nGUIDE\n.
_GUIDE_CARD_START_RE = re.compile(
    r"(?:^|\n\n)GUIDE\n",
)


# -- Section boundary markers -------------------------------------------------
#
# Actual pdfplumber column headers (from VPS):
#   Yellow: "ID Guide Name of Material" (No. is on next line)
#   Blue:   "Name of Material Guide ID" (No. is on next line)

_YELLOW_MARKERS = [
    # pdfplumber merges column header words: "ID Guide Name of Material"
    # (the "No." for each column appears on the following line)
    re.compile(r"ID Guide Name of Material", re.IGNORECASE),
    re.compile(r"ID\s*No\.?\s+Guide\s*No\.?\s+Name\s+of\s+Material", re.IGNORECASE),
    re.compile(r"UN/NA\s+ID\s+NUMBER\s+INDEX", re.IGNORECASE),
]

_BLUE_MARKERS = [
    # pdfplumber: "Name of Material Guide ID"
    re.compile(r"Name of Material Guide ID", re.IGNORECASE),
    re.compile(r"Name\s+of\s+Material\s+Guide\s*No", re.IGNORECASE),
    re.compile(r"MATERIAL\s+NAME\s+INDEX", re.IGNORECASE),
]

_GREEN_MARKERS = [
    re.compile(r"TABLE\s+1\b.*INITIAL\s+ISOLATION", re.IGNORECASE),
    re.compile(r"ISOLATION\s+AND\s+PROTECTIVE\s+ACTION\s+DISTANCES", re.IGNORECASE),
    re.compile(r"INITIAL\s+ISOLATION\s+AND\s+PROTECTIVE", re.IGNORECASE),
]

_BACK_MARKERS = [
    re.compile(r"CRIMINAL/TERRORIST\s+USE", re.IGNORECASE),
    re.compile(r"IMPROVISED\s+EXPLOSIVE\s+DEVICE", re.IGNORECASE),
    re.compile(r"IED\s+SAFE\s+STANDOFF", re.IGNORECASE),
    re.compile(r"GLOSSARY", re.IGNORECASE),
    re.compile(r"EMERGENCY\s+RESPONSE\s+TELEPHONE", re.IGNORECASE),
]


def _is_guide_page(text: str) -> bool:
    """Return True if a page looks like an Orange Guide card."""
    # GUIDE must be on its own line (not part of "Guide No." column header)
    has_guide = bool(re.search(r"^GUIDE$", text, re.MULTILINE))
    has_hazards = bool(re.search(
        r"POTENTIAL\s+HAZARDS|EMERGENCY\s+RESPONSE", text,
    ))
    # Guide number (3 digits) on its own line
    has_number = bool(re.search(r"^\d{3}$", text, re.MULTILINE))
    return has_guide and has_hazards and has_number


# -- Public API ---------------------------------------------------------------

def parse_source(pdf_path: Path) -> list[Section]:
    """Parse the ERG 2024 PDF and return Section objects."""
    pages = _extract_pages(pdf_path)
    if not pages:
        raise ValueError(f"No text extracted from {pdf_path}")

    total_chars = sum(len(p) for p in pages)
    non_empty = sum(1 for p in pages if p.strip())
    logger.warning(
        "ERG: extracted %d pages (%d non-empty, %d total chars)",
        len(pages), non_empty, total_chars,
    )

    for sample_page in (0, 30, 100, 170, 290):
        if sample_page < len(pages):
            snippet = pages[sample_page][:120].replace("\n", "\\n")
            logger.warning("ERG page %d: %s", sample_page, snippet)

    boundaries = _detect_boundaries(pages)

    sections: list[Section] = []
    sections.extend(_parse_orange_guides(pages, boundaries))
    sections.extend(_parse_yellow_section(pages, boundaries))
    sections.extend(_parse_blue_section(pages, boundaries))
    sections.extend(_parse_green_section(pages, boundaries))
    sections.extend(_parse_white_section(pages, boundaries))
    sections.extend(_parse_back_matter(pages, boundaries))

    if not sections:
        logger.warning("ERG: all parsers returned 0 -- falling back to whole-doc chunking")
        full_text = _page_range(pages, 0, len(pages))
        sections = _chunk_text_blocks(full_text, "Full", "ERG 2024", chunk_lines=60)

    logger.warning("ERG: %d total sections produced", len(sections))
    return sections


# -- PDF text extraction -------------------------------------------------------

class _PageExtractionTimeout(Exception):
    pass


def _alarm_handler(signum, frame):
    raise _PageExtractionTimeout()


def _extract_pages(pdf_path: Path) -> list[str]:
    """Extract text from every page using pdfplumber.

    Uses SIGALRM (Unix) to enforce a per-page timeout.  Complex graphical
    pages (placard tables, rail car diagrams) can cause pdfplumber to hang
    indefinitely; SIGALRM cleanly interrupts the extraction so the process
    can move on.
    """
    pages: list[str] = []
    timeouts = 0
    errors = 0
    use_alarm = hasattr(signal, "SIGALRM")

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        logger.warning(
            "ERG: extracting %d pages (timeout=%ds/page, alarm=%s)...",
            total, _PAGE_TIMEOUT, use_alarm,
        )

        for i, page in enumerate(pdf.pages):
            old_handler = None
            try:
                if use_alarm:
                    old_handler = signal.signal(signal.SIGALRM, _alarm_handler)
                    signal.alarm(_PAGE_TIMEOUT)

                text = page.extract_text() or ""

                if use_alarm:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)

            except _PageExtractionTimeout:
                text = ""
                timeouts += 1
                if use_alarm:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                if timeouts <= 10:
                    logger.warning(
                        "ERG: page %d timed out after %ds (complex graphics)",
                        i, _PAGE_TIMEOUT,
                    )

            except Exception as exc:
                text = ""
                errors += 1
                if use_alarm and old_handler is not None:
                    signal.alarm(0)
                    signal.signal(signal.SIGALRM, old_handler)
                if errors <= 5:
                    logger.warning("ERG: page %d extraction error: %s", i, exc)

            pages.append(text)

            if (i + 1) % 50 == 0:
                logger.warning("ERG: extracted %d/%d pages...", i + 1, total)

    if timeouts:
        logger.warning(
            "ERG: %d/%d pages timed out (skipped)", timeouts, len(pages),
        )
    if errors:
        logger.warning("ERG: %d/%d pages had errors", errors, len(pages))

    return pages


# -- Section boundary detection ------------------------------------------------

def _any_marker_match(markers: list[re.Pattern], text: str) -> bool:
    return any(m.search(text) for m in markers)


def _detect_boundaries(pages: list[str]) -> dict[str, int]:
    """Scan pages for section-start markers.  Returns page indices."""
    boundaries: dict[str, int] = {
        "yellow": -1,
        "blue": -1,
        "orange": -1,
        "green": -1,
        "back": -1,
    }

    n = len(pages)

    for i, text in enumerate(pages):
        if not text.strip():
            continue

        if boundaries["yellow"] < 0 and i < n * 0.15:
            if _any_marker_match(_YELLOW_MARKERS, text):
                boundaries["yellow"] = i

        if boundaries["blue"] < 0 and i > n * 0.2 and i < n * 0.45:
            if _any_marker_match(_BLUE_MARKERS, text):
                boundaries["blue"] = i

        if boundaries["orange"] < 0 and i > n * 0.3:
            if _is_guide_page(text):
                boundaries["orange"] = i

        if boundaries["green"] < 0 and i > n * 0.6:
            if _any_marker_match(_GREEN_MARKERS, text):
                boundaries["green"] = i

        if boundaries["back"] < 0 and i > n * 0.8:
            if _any_marker_match(_BACK_MARKERS, text):
                boundaries["back"] = i

    # Fallback: hardcoded page-fraction estimates for ERG 2024 (392 pages)
    fallback_fractions = {
        "yellow": 0.07,
        "blue":   0.33,
        "orange": 0.42,
        "green":  0.73,
        "back":   0.92,
    }

    for key, frac in fallback_fractions.items():
        if boundaries[key] < 0:
            fallback_page = int(n * frac)
            logger.warning(
                "ERG: '%s' not detected -- fallback page %d (%.0f%%)",
                key, fallback_page, frac * 100,
            )
            boundaries[key] = fallback_page

    # Enforce monotonic ordering
    ordered = ["yellow", "blue", "orange", "green", "back"]
    for j in range(1, len(ordered)):
        if boundaries[ordered[j]] <= boundaries[ordered[j - 1]]:
            boundaries[ordered[j]] = boundaries[ordered[j - 1]] + 1

    logger.warning("ERG boundaries: %s", boundaries)
    return boundaries


# -- Helpers -------------------------------------------------------------------

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
    return "\n\n".join(pages[start:end])


# -- Orange Guide parsing (highest priority) -----------------------------------

def _parse_orange_guides(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    """Parse the 62 Emergency Response Guide cards (Guides 111-175).

    pdfplumber format per page:
      "GUIDE\\n{title}\\n{number}\\nPOTENTIAL HAZARDS\\n..."
    or on the response side:
      "GUIDE\\n{title}\\n{number}\\nEMERGENCY RESPONSE\\n..."
    """
    start = boundaries["orange"]
    end = boundaries["green"]

    orange_text = _page_range(pages, start, end)
    if not orange_text.strip():
        logger.warning("ERG: orange section empty (pages %d-%d)", start, end)
        return []

    # Strategy 1: Split by "GUIDE\n" (GUIDE on its own line, newline after).
    # Each guide card has this on both pages of the 2-page spread.
    splits = list(_GUIDE_CARD_START_RE.finditer(orange_text))
    logger.warning(
        "ERG orange: %d 'GUIDE\\n' splits in %d chars of pages %d-%d",
        len(splits), len(orange_text), start, end,
    )

    if splits:
        # Extract guide number from each split region, then merge the two
        # pages of each guide (POTENTIAL HAZARDS + EMERGENCY RESPONSE).
        guide_regions: dict[str, list[str]] = {}

        for idx, match in enumerate(splits):
            region_start = match.start()
            region_end = (
                splits[idx + 1].start()
                if idx + 1 < len(splits)
                else len(orange_text)
            )
            region_text = orange_text[region_start:region_end].strip()
            if not region_text:
                continue

            # Look for the guide number on its own line before POTENTIAL/EMERGENCY
            num_match = _GUIDE_NUM_LINE_RE.search(region_text)
            if num_match:
                gn = int(num_match.group(1))
                if 111 <= gn <= 175:
                    guide_regions.setdefault(str(gn), []).append(region_text)
                    continue

            # Fallback: any 3-digit number on its own line
            line_num = re.search(r"^(\d{3})$", region_text, re.MULTILINE)
            if line_num:
                gn = int(line_num.group(1))
                if 111 <= gn <= 175:
                    guide_regions.setdefault(str(gn), []).append(region_text)
                    continue

        # Merge the (typically 2) pages per guide into one section
        sections: list[Section] = []
        for guide_num in sorted(guide_regions.keys(), key=int):
            parts = guide_regions[guide_num]
            merged_text = "\n\n".join(parts)
            title = _extract_guide_title(merged_text, guide_num)

            sections.append(_make_section(
                section_number=f"ERG Guide {guide_num}",
                section_title=title,
                full_text=merged_text,
                parent="ERG Orange Section",
            ))

        if sections:
            logger.warning("ERG: parsed %d Orange Guide cards", len(sections))
            return sections

    # Strategy 2: Split by "POTENTIAL HAZARDS" markers
    hazard_re = re.compile(r"POTENTIAL\s+HAZARDS", re.IGNORECASE)
    hazard_matches = list(hazard_re.finditer(orange_text))
    if hazard_matches:
        logger.warning(
            "ERG: guide splitting failed, using %d POTENTIAL HAZARDS markers",
            len(hazard_matches),
        )
        sections = []
        for idx, match in enumerate(hazard_matches):
            chunk_start = match.start()
            chunk_end = (
                hazard_matches[idx + 1].start()
                if idx + 1 < len(hazard_matches)
                else len(orange_text)
            )
            chunk_text = orange_text[chunk_start:chunk_end].strip()
            if chunk_text:
                num_m = re.search(r"^(\d{3})$", chunk_text, re.MULTILINE)
                gn = num_m.group(1) if num_m else str(111 + idx)
                sections.append(_make_section(
                    section_number=f"ERG Guide {gn}",
                    section_title=f"Emergency Response Guide {gn}",
                    full_text=chunk_text,
                    parent="ERG Orange Section",
                ))
        if sections:
            return sections

    # Strategy 3: Chunk as text blocks
    logger.warning("ERG: no guide markers found -- chunking orange as blocks")
    return _chunk_text_blocks(
        orange_text, "Orange", "Emergency Response Guides", chunk_lines=60,
    )


def _extract_guide_title(text: str, guide_num: str) -> str:
    """Extract the hazard class title from a guide card's text.

    pdfplumber format: "GUIDE\\n{title}\\n{number}\\nPOTENTIAL HAZARDS"
    """
    # Pattern: title is between "GUIDE\n" and "\n{number}\n"
    m = _GUIDE_TITLE_EXTRACT_RE.search(text)
    if m:
        title = m.group(1).strip()
        title = re.sub(r"\s*\n\s*", " ", title)
        if len(title) > 120:
            title = title[:117] + "..."
        return title

    # Fallback: grab text between GUIDE and POTENTIAL/EMERGENCY
    m = re.search(
        r"GUIDE\n(.+?)(?:\nPOTENTIAL|\nEMERGENCY)", text, re.DOTALL,
    )
    if m:
        title = m.group(1).strip()
        # Remove the guide number if present
        title = re.sub(r"\n?\d{3}\s*$", "", title).strip()
        title = re.sub(r"\s*\n\s*", " ", title)
        if len(title) > 120:
            title = title[:117] + "..."
        return title

    return f"Guide {guide_num}"


# -- Yellow Section (ID Number -> Guide lookup) --------------------------------

def _parse_yellow_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["yellow"]
    end = boundaries["blue"]

    yellow_text = _page_range(pages, start, end)
    if not yellow_text.strip():
        logger.warning("ERG: yellow section empty")
        return []
    return _chunk_tabular_by_id(yellow_text, "Yellow", "ID Number Index")


def _chunk_tabular_by_id(
    full_text: str, color: str, index_label: str,
) -> list[Section]:
    """Chunk tabular ID/Guide/Name data in groups of ~28 entries."""
    entry_patterns = [
        re.compile(r"^((?:UN|NA)\d{4})\s+(\d{3})\s+(.+)$", re.MULTILINE),
        re.compile(r"((?:UN|NA)\d{4})\s{2,}(\d{3})\s{2,}(.+?)$", re.MULTILINE),
        # ERG yellow/blue may not have UN/NA prefix -- just 4-digit ID + 3-digit guide
        re.compile(r"(\d{4})\s+(\d{3})\s+([A-Z].{5,})", re.MULTILINE),
        # Minimal: just find UN/NA IDs
        re.compile(r"((?:UN|NA)\d{4})", re.MULTILINE),
    ]

    entries = None
    for pattern in entry_patterns:
        matches = list(pattern.finditer(full_text))
        if len(matches) >= 10:
            entries = matches
            logger.warning(
                "ERG %s: %d entries via pattern %s",
                color, len(matches), pattern.pattern[:50],
            )
            break

    if not entries:
        logger.warning("ERG: no tabular entries in %s -- using blocks", color)
        return _chunk_text_blocks(full_text, color, index_label, chunk_lines=60)

    sections: list[Section] = []
    group_size = 28

    for i in range(0, len(entries), group_size):
        batch = entries[i : i + group_size]
        first_id = batch[0].group(1)
        last_id = batch[-1].group(1)

        text_start = batch[0].start()
        text_end = (
            entries[i + group_size].start()
            if i + group_size < len(entries)
            else len(full_text)
        )
        chunk_text = full_text[text_start:text_end].strip()

        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG {color} {first_id}-{last_id}",
                section_title=f"{index_label}: {first_id} to {last_id}",
                full_text=chunk_text,
                parent=f"ERG {color} Section",
            ))

    logger.warning("ERG: parsed %d %s section chunks", len(sections), color)
    return sections


# -- Blue Section (Name -> Guide lookup) ---------------------------------------

def _parse_blue_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["blue"]
    end = boundaries["orange"]

    blue_text = _page_range(pages, start, end)
    if not blue_text.strip():
        logger.warning("ERG: blue section empty")
        return []

    return _chunk_tabular_by_id(blue_text, "Blue", "Material Name Index")


# -- Green Section (Isolation & Protection Tables) -----------------------------

_TABLE_NUM_RE = re.compile(r"TABLE\s+(\d)", re.IGNORECASE)


def _parse_green_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["green"]
    end = boundaries["back"]

    green_text = _page_range(pages, start, end)
    if not green_text.strip():
        logger.warning("ERG: green section empty")
        return []

    table_splits = list(_TABLE_NUM_RE.finditer(green_text))

    if len(table_splits) < 2:
        return _chunk_text_blocks(
            green_text, "Green",
            "Isolation & Protective Action Distances", chunk_lines=50,
        )

    sections: list[Section] = []
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

    logger.warning("ERG: parsed %d Green section chunks", len(sections))
    return sections


def _chunk_green_table_by_id(
    text: str, table_num: str, title_prefix: str,
) -> list[Section]:
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
        text_end = (
            entries[i + group_size].start()
            if i + group_size < len(entries)
            else len(text)
        )
        chunk_text = text[text_start:text_end].strip()

        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG Table {table_num} {first_id}-{last_id}",
                section_title=f"{title_prefix}: {first_id} to {last_id}",
                full_text=chunk_text,
                parent="ERG Green Section",
            ))

    return sections


# -- White Section (Front Matter) ----------------------------------------------

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


def _parse_white_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    end = boundaries["yellow"]

    white_text = _page_range(pages, 0, end)
    if not white_text.strip():
        logger.warning("ERG: white section empty")
        return []

    topic_spans: list[tuple[str, int, int]] = []
    for topic_name, pattern in _WHITE_TOPICS:
        match = pattern.search(white_text)
        if match:
            topic_spans.append((topic_name, match.start(), -1))

    if not topic_spans:
        return _chunk_text_blocks(white_text, "White", "Front Matter", chunk_lines=80)

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
                parent="ERG White Section",
            ))

    if topic_spans and topic_spans[0][1] > 200:
        preamble = white_text[: topic_spans[0][1]].strip()
        if preamble:
            sections.insert(0, _make_section(
                section_number="ERG How to Use This Guidebook",
                section_title="How to Use This Guidebook",
                full_text=preamble,
                parent="ERG White Section",
            ))

    logger.warning("ERG: parsed %d White section chunks", len(sections))
    return sections


# -- Back Matter ---------------------------------------------------------------

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


def _parse_back_matter(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["back"]

    back_text = _page_range(pages, start, len(pages))
    if not back_text.strip():
        logger.warning("ERG: back matter empty")
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

        if name == "Glossary" and len(chunk_text) > 3000:
            mid = len(chunk_text) // 2
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

    logger.warning("ERG: parsed %d Back Matter chunks", len(sections))
    return sections


# -- Generic text block chunker (fallback) -------------------------------------

def _chunk_text_blocks(
    text: str,
    color: str,
    label: str,
    chunk_lines: int = 60,
) -> list[Section]:
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

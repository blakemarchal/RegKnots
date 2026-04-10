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

pdfplumber output format (from actual VPS extraction):
  Page 170: "GUIDE  Gases - Toxic - Flammable  119  EMERGENCY RESPONSE  FIRE..."
  i.e., format is  GUIDE  {title}  {number}  — the number comes AFTER the title.
"""

import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import date
from pathlib import Path

import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "erg"
TITLE_NUMBER = 0
SOURCE_DATE = date(2024, 10, 1)  # ERG 2024 publication date

# Per-page extraction timeout in seconds.  Most pages extract in <0.5s but
# complex graphical pages (placard tables, rail car diagrams) can hang
# pdfplumber indefinitely.
_PAGE_TIMEOUT = 10

# ── Orange Guide detection ───────────────────────────────────────────────────
#
# pdfplumber output for guide pages is:
#   "GUIDE  {hazard class title}  {3-digit number}  POTENTIAL HAZARDS ..."
# or on the response page:
#   "GUIDE  {hazard class title}  {3-digit number}  EMERGENCY RESPONSE ..."
#
# The guide number comes AFTER the title, NOT right after "GUIDE".

# Finds a 3-digit guide number (111-175) followed by POTENTIAL HAZARDS or
# EMERGENCY RESPONSE — the definitive marker of a guide card page.
_GUIDE_NUM_AFTER_TITLE_RE = re.compile(
    r"\b(\d{3})\s{2,}(?:POTENTIAL\s+HAZARDS|EMERGENCY\s+RESPONSE)",
)

# Broader: find "GUIDE" followed by title text then a 3-digit number
_GUIDE_WITH_TITLE_RE = re.compile(
    r"GUIDE\s{2,}(.{3,80}?)\s{2,}(\d{3})\b",
)

# For splitting: each guide card starts with "GUIDE" followed by an uppercase
# title.  We split on this pattern to separate individual guides.
_GUIDE_CARD_START_RE = re.compile(
    r"(?:^|\n\n?)GUIDE\s{2,}[A-Z]",
)

# ── Section boundary markers ────────────────────────────────────────────────

_YELLOW_MARKERS = [
    re.compile(r"ID\s*No\.?\s+Guide\s*No\.?\s+Name\s+of\s+Material", re.IGNORECASE),
    re.compile(r"UN/NA\s+ID\s+NUMBER\s+INDEX", re.IGNORECASE),
    re.compile(r"ID\s+No\.\s+Guide", re.IGNORECASE),
    re.compile(r"(?:UN|NA)\d{4}\s+\d{3}\s+.{5,}"),
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

# ── Orange-section page detector (for boundary detection) ───────────────────

def _is_guide_page(text: str) -> bool:
    """Return True if a page looks like an Orange Guide card."""
    has_guide = bool(re.search(r"\bGUIDE\b", text))
    has_hazards = bool(re.search(
        r"POTENTIAL\s+HAZARDS|EMERGENCY\s+RESPONSE", text,
    ))
    has_number = bool(re.search(r"\b1[1-7]\d\b", text))
    return has_guide and has_hazards and has_number


# ── Public API ───────────────────────────────────────────────────────────────

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

    # Log samples at WARNING level so they're always visible
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

    # Safety net: never return 0 sections
    if not sections:
        logger.warning(
            "ERG: all section parsers returned 0 — "
            "falling back to whole-document chunking"
        )
        full_text = _page_range(pages, 0, len(pages))
        sections = _chunk_text_blocks(
            full_text, "Full", "ERG 2024", chunk_lines=60,
        )

    logger.warning("ERG: %d total sections produced", len(sections))
    return sections


# ── PDF text extraction ──────────────────────────────────────────────────────

def _extract_one_page(page) -> str:
    """Extract text from a single pdfplumber page (runs in thread pool)."""
    return page.extract_text() or ""


def _extract_pages(pdf_path: Path) -> list[str]:
    """Extract text from every page using pdfplumber.

    Uses a per-page timeout to handle complex graphical pages that cause
    pdfplumber to hang (e.g., placard tables, rail car diagrams).
    """
    pages: list[str] = []
    timeouts = 0
    errors = 0

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        logger.warning("ERG: extracting %d pages (timeout=%ds/page)...", total, _PAGE_TIMEOUT)

        with ThreadPoolExecutor(max_workers=1) as executor:
            for i, page in enumerate(pdf.pages):
                try:
                    future = executor.submit(_extract_one_page, page)
                    text = future.result(timeout=_PAGE_TIMEOUT)
                except FuturesTimeout:
                    text = ""
                    timeouts += 1
                    if timeouts <= 10:
                        logger.warning(
                            "ERG: page %d timed out after %ds (likely complex graphics)",
                            i, _PAGE_TIMEOUT,
                        )
                    # Cancel the hung future — the worker thread may still be
                    # running but we move on.  Create a fresh executor to avoid
                    # blocking on the stuck thread.
                    future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    executor = ThreadPoolExecutor(max_workers=1)
                except Exception as exc:
                    text = ""
                    errors += 1
                    if errors <= 5:
                        logger.warning("ERG: page %d extraction error: %s", i, exc)
                pages.append(text)

                # Progress logging every 50 pages
                if (i + 1) % 50 == 0:
                    logger.warning("ERG: extracted %d/%d pages...", i + 1, total)

    if timeouts:
        logger.warning(
            "ERG: %d/%d pages timed out (skipped — graphical pages)",
            timeouts, len(pages),
        )
    if errors:
        logger.warning("ERG: %d/%d pages had extraction errors", errors, len(pages))

    return pages


# ── Section boundary detection ───────────────────────────────────────────────

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

        if boundaries["yellow"] < 0 and _any_marker_match(_YELLOW_MARKERS, text):
            boundaries["yellow"] = i

        if boundaries["blue"] < 0 and _any_marker_match(_BLUE_MARKERS, text):
            if boundaries["yellow"] >= 0 and i > boundaries["yellow"]:
                boundaries["blue"] = i

        # Orange: look for actual guide card pages (GUIDE + number + HAZARDS)
        if boundaries["orange"] < 0 and _is_guide_page(text):
            if i > n * 0.3:
                boundaries["orange"] = i

        if boundaries["green"] < 0 and _any_marker_match(_GREEN_MARKERS, text):
            if i > n * 0.6:
                boundaries["green"] = i

        if boundaries["back"] < 0 and _any_marker_match(_BACK_MARKERS, text):
            if i > n * 0.8:
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
                "ERG: regex detection failed for '%s' — "
                "using fallback page %d (%.0f%% of %d)",
                key, fallback_page, frac * 100, n,
            )
            boundaries[key] = fallback_page

    # Enforce monotonic ordering
    ordered = ["yellow", "blue", "orange", "green", "back"]
    for j in range(1, len(ordered)):
        if boundaries[ordered[j]] <= boundaries[ordered[j - 1]]:
            boundaries[ordered[j]] = boundaries[ordered[j - 1]] + 1

    logger.warning("ERG boundaries: %s", boundaries)
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
    return "\n\n".join(pages[start:end])


# ── Orange Guide parsing (highest priority) ─────────────────────────────────

def _parse_orange_guides(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    """Parse the 62 Emergency Response Guide cards (Guides 111-175).

    pdfplumber format per page:
      "GUIDE  {title}  {number}  POTENTIAL HAZARDS ..."
    or on the response side:
      "GUIDE  {title}  {number}  EMERGENCY RESPONSE ..."
    """
    start = boundaries["orange"]
    end = boundaries["green"]

    orange_text = _page_range(pages, start, end)
    if not orange_text.strip():
        logger.warning("ERG: orange section text is empty (pages %d-%d)", start, end)
        return []

    # Strategy 1: Split by "GUIDE  {uppercase title}" pattern.  Each guide
    # card (2-page spread) starts with this.  Both pages of the spread have
    # it, so we'll see ~124 splits for 62 guides.
    splits = list(_GUIDE_CARD_START_RE.finditer(orange_text))
    logger.warning(
        "ERG orange: found %d 'GUIDE  [A-Z]' splits in %d chars",
        len(splits), len(orange_text),
    )

    if splits:
        # Extract guide number from each split region, then merge the two
        # pages of each guide into a single section.
        guide_regions: dict[str, list[str]] = {}  # guide_num → [text, ...]

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

            # Extract the guide number: look for 3-digit number in range
            num_match = _GUIDE_NUM_AFTER_TITLE_RE.search(region_text)
            if not num_match:
                # Fallback: find any 3-digit number after "GUIDE"
                num_match = _GUIDE_WITH_TITLE_RE.search(region_text)

            if num_match:
                # _GUIDE_NUM_AFTER_TITLE_RE has number in group 1
                # _GUIDE_WITH_TITLE_RE has number in group 2
                raw_num = num_match.group(num_match.lastindex)
                try:
                    gn = int(raw_num)
                except ValueError:
                    continue
                if 111 <= gn <= 175:
                    guide_num = str(gn)
                    guide_regions.setdefault(guide_num, []).append(region_text)
                    continue

            # Couldn't extract a guide number — try brute force
            for m in re.finditer(r"\b(1[1-7]\d)\b", region_text):
                gn = int(m.group(1))
                if 111 <= gn <= 175:
                    guide_regions.setdefault(str(gn), []).append(region_text)
                    break

        # Merge the (typically 2) pages per guide into one section
        sections: list[Section] = []
        for guide_num in sorted(guide_regions.keys(), key=int):
            parts = guide_regions[guide_num]
            merged_text = "\n\n".join(parts)

            # Extract title from the GUIDE header
            title = _extract_guide_title(merged_text, guide_num)

            sections.append(_make_section(
                section_number=f"ERG Guide {guide_num}",
                section_title=title,
                full_text=merged_text,
                parent="ERG Orange Section — Emergency Response Guides",
            ))

        if sections:
            logger.warning("ERG: parsed %d Orange Guide cards", len(sections))
            return sections

    # Strategy 2: Split by "POTENTIAL HAZARDS" markers
    hazard_re = re.compile(r"POTENTIAL\s+HAZARDS", re.IGNORECASE)
    hazard_matches = list(hazard_re.finditer(orange_text))
    if hazard_matches:
        logger.warning(
            "ERG: guide-card splitting failed, using %d POTENTIAL HAZARDS markers",
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
                # Try to find guide number in this chunk
                num_m = re.search(r"\b(1[1-7]\d)\b", chunk_text)
                guide_num = num_m.group(1) if num_m else str(111 + idx)
                sections.append(_make_section(
                    section_number=f"ERG Guide {guide_num}",
                    section_title=f"Emergency Response Guide {guide_num}",
                    full_text=chunk_text,
                    parent="ERG Orange Section — Emergency Response Guides",
                ))
        if sections:
            return sections

    # Strategy 3: Chunk as text blocks
    logger.warning("ERG: no guide markers found — chunking orange as blocks")
    return _chunk_text_blocks(
        orange_text, "Orange", "Emergency Response Guides", chunk_lines=60,
    )


def _extract_guide_title(text: str, guide_num: str) -> str:
    """Extract the hazard class title from a guide card's text.

    pdfplumber format: "GUIDE  {title}  {number}  POTENTIAL HAZARDS"
    """
    # Pattern 1: "GUIDE  Title Text  NNN" — title is between GUIDE and number
    m = _GUIDE_WITH_TITLE_RE.search(text)
    if m:
        title = m.group(1).strip()
        title = re.sub(r"\s{2,}", " ", title)
        if len(title) > 120:
            title = title[:117] + "..."
        return title

    # Pattern 2: grab text between "GUIDE" and "POTENTIAL HAZARDS"
    m = re.search(
        r"GUIDE\s{2,}(.+?)\s{2,}(?:POTENTIAL\s+HAZARDS|EMERGENCY\s+RESPONSE)",
        text, re.DOTALL,
    )
    if m:
        title = m.group(1).strip()
        # Remove the guide number if it's at the end
        title = re.sub(r"\s+\d{3}\s*$", "", title)
        title = re.sub(r"\s{2,}", " ", title)
        if len(title) > 120:
            title = title[:117] + "..."
        return title

    return f"Guide {guide_num}"


# ── Yellow Section (ID Number → Guide lookup) ───────────────────────────────

def _parse_yellow_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["yellow"]
    end = boundaries["blue"]

    yellow_text = _page_range(pages, start, end)
    if not yellow_text.strip():
        logger.warning("ERG: yellow section text is empty")
        return []
    return _chunk_tabular_by_id(yellow_text, "Yellow", "ID Number Index")


def _chunk_tabular_by_id(
    full_text: str, color: str, index_label: str,
) -> list[Section]:
    """Chunk tabular ID/Guide/Name data in groups of ~28 entries."""
    entry_patterns = [
        re.compile(r"^((?:UN|NA)\d{4})\s+(\d{3})\s+(.+)$", re.MULTILINE),
        re.compile(r"((?:UN|NA)\d{4})\s{2,}(\d{3})\s{2,}(.+?)$", re.MULTILINE),
        re.compile(r"((?:UN|NA)\d{4})", re.MULTILINE),
    ]

    entries = None
    for pattern in entry_patterns:
        matches = list(pattern.finditer(full_text))
        if len(matches) >= 10:
            entries = matches
            break

    if not entries:
        logger.warning("ERG: no tabular entries in %s section — using blocks", color)
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


# ── Blue Section (Name → Guide lookup) ───────────────────────────────────────

def _parse_blue_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["blue"]
    end = boundaries["orange"]

    blue_text = _page_range(pages, start, end)
    if not blue_text.strip():
        logger.warning("ERG: blue section text is empty")
        return []

    entry_patterns = [
        re.compile(r"^(.{10,60}?)\s{2,}(\d{3})\s+((?:UN|NA)\d{4})\s*$", re.MULTILINE),
        re.compile(r"(.{10,60}?)\s{2,}(\d{3})\s{2,}((?:UN|NA)\d{4})", re.MULTILINE),
        re.compile(r"((?:UN|NA)\d{4})", re.MULTILINE),
    ]

    entries = None
    for pattern in entry_patterns:
        matches = list(pattern.finditer(blue_text))
        if len(matches) >= 10:
            entries = matches
            break

    if not entries:
        logger.warning("ERG: no entries in Blue section — using blocks")
        return _chunk_text_blocks(blue_text, "Blue", "Material Name Index", chunk_lines=60)

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
            else len(blue_text)
        )
        chunk_text = blue_text[text_start:text_end].strip()

        if chunk_text:
            sections.append(_make_section(
                section_number=f"ERG Blue {first_id}-{last_id}",
                section_title=f"Material Name Index: {first_id} to {last_id}",
                full_text=chunk_text,
                parent="ERG Blue Section",
            ))

    logger.warning("ERG: parsed %d Blue section chunks", len(sections))
    return sections


# ── Green Section (Isolation & Protection Tables) ────────────────────────────

_TABLE_NUM_RE = re.compile(r"TABLE\s+(\d)", re.IGNORECASE)


def _parse_green_section(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
    start = boundaries["green"]
    end = boundaries["back"]

    green_text = _page_range(pages, start, end)
    if not green_text.strip():
        logger.warning("ERG: green section text is empty")
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


# ── White Section (Front Matter) ─────────────────────────────────────────────

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
        logger.warning("ERG: white section text is empty")
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
                parent="ERG White Section — Front Matter",
            ))

    if topic_spans and topic_spans[0][1] > 200:
        preamble = white_text[: topic_spans[0][1]].strip()
        if preamble:
            sections.insert(0, _make_section(
                section_number="ERG How to Use This Guidebook",
                section_title="How to Use This Guidebook",
                full_text=preamble,
                parent="ERG White Section — Front Matter",
            ))

    logger.warning("ERG: parsed %d White section chunks", len(sections))
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


def _parse_back_matter(
    pages: list[str], boundaries: dict[str, int],
) -> list[Section]:
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


# ── Generic text block chunker (fallback) ────────────────────────────────────

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

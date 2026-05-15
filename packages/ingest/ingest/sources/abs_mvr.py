"""ABS Marine Vessel Rules (MVR) adapter.

Sprint D6.93 — first American Bureau of Shipping class-society
adapter. ABS classes ~70% of US-flag commercial vessels; the MVR is
the consolidated rule set covering hull construction, machinery,
electrical engineering, survey schedules, and ship-type-specific
requirements. Free and publicly downloadable from the
ww2.eagle.org CDN — no auth, no paywall, no ToS issue with caching.

Source files: ``data/raw/abs/*.pdf``. Filename convention is
``1-mvr-part-N-jul25.pdf`` (or ``part-5c1``, ``part-5c2``, etc.) plus
auxiliary ``1-mvr-nandgi-jul25.pdf`` (Notices and General Information)
and ``class-notations-table-jul25.pdf``.

Chunking strategy
-----------------
ABS uses Part / Chapter / Section / Sub-section hierarchy. Each PDF
is a single Part (e.g. Part 3 Hull Construction, Part 4 Vessel
Systems & Machinery). The text contains explicit headers in the
shape:

    SECTION 1   Engineering Systems Overview
    Section 1   Engineering Systems Overview
    1.1  Goal
    1.1.1  Goal Statement.

We chunk at the Section level — granular enough that individual
queries can resolve to the right ~1-3 page block, coarse enough that
the section_number text matches what mariners actually write (e.g.
"ABS MVR Pt.4 Ch.2 Sec.1"). Sub-section numbering (1.1.1) stays
inside the parent section's body text.

Section number format (citation-friendly)
-----------------------------------------
    "ABS MVR Pt.4 Ch.2 Sec.1"

The frontend citation regex parses this same shape so a chat answer
that says "per ABS MVR Pt.4 Ch.2 Sec.1" renders as a clickable chip.
"""
from __future__ import annotations

import logging
import re
import subprocess
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "abs_mvr"
TITLE_NUMBER = 0
# Per the July 2025 edition stamp in the file names.
SOURCE_DATE = date(2025, 7, 1)

# Parse the part number from the file stem. Examples:
#   "1-mvr-part-3-jul25" → "3"
#   "1-mvr-part-5c1-jul25" → "5C1" (uppercase the variant suffix)
#   "1-mvr-nandgi-jul25"   → "NandGI"
#   "class-notations-table-jul25" → "Notations"
_PART_FROM_NAME = re.compile(
    r"^1-mvr-part-([\dA-Za-z]+)-",
    re.IGNORECASE,
)

# Chapter header inside the text. ABS uses both upper-case ("CHAPTER 3")
# in body banners and title-case ("Chapter 3") in cross-references and
# the front-matter table of contents.
_CHAPTER_HEADER = re.compile(
    r"^\s*CHAPTER\s+(\d+)\s+(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Section header inside the text. Same case-variance applies. The
# trailing portion of the line may include TOC leader dots and a page
# number (e.g. "Section 3   Engineering Systems Overview...........5");
# we exclude those at split time by checking the captured title for a
# leader-dot run — see _split_into_sections.
_SECTION_HEADER = re.compile(
    r"^\s*Section\s+(\d+)\s+(.+?)\s*$",
    re.MULTILINE | re.IGNORECASE,
)

# Lines that look like TOC entries inside a captured section title —
# title text followed by leader dots and a page number. We treat any
# match with 4+ consecutive dots as a TOC false positive.
_TOC_LEADER = re.compile(r"\.{4,}")

# PDF noise patterns — header footers, page numbers, ABS branding.
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$", re.MULTILINE)
_ABS_FOOTER = re.compile(
    r"^.*(?:ABS\s+RULES?\s+FOR|MARINE\s+VESSEL\s+RULES|Part\s+\d+,?\s+Chapter\s+\d+).*$",
    re.MULTILINE,
)
_REPEAT_DASH = re.compile(r"^[\-–—]{4,}\s*$", re.MULTILINE)


def _clean_text(text: str) -> str:
    """Strip PDF noise — page numbers, repeated headers, separator lines."""
    text = text.replace("\x00", "")
    text = _PAGE_NUMBER.sub("", text)
    text = _ABS_FOOTER.sub("", text)
    text = _REPEAT_DASH.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _detect_part(pdf_path: Path) -> str:
    """Return a citation-friendly Part identifier for the given PDF."""
    name = pdf_path.stem.lower()
    m = _PART_FROM_NAME.match(name)
    if m:
        return m.group(1).upper()
    if "nandgi" in name:
        return "Notices"
    if "notations" in name:
        return "Notations"
    return pdf_path.stem


def _dedupe_consecutive_same_number(matches: list) -> list:
    """ABS rule books repeat the chapter/section banner on every page as
    a running header. With pdftotext output, this produces many
    consecutive regex matches with the same number (e.g. ten ``CHAPTER 1
    General`` matches inside Chapter 1, then one ``CHAPTER 2``, then
    fifteen ``CHAPTER 2 ...`` etc.). Slicing on every match shreds the
    body into page-sized fragments and most sub-sections fall on the
    seams. Keep only the first match in each consecutive run.
    """
    if not matches:
        return []
    out = [matches[0]]
    for m in matches[1:]:
        if m.group(1) == out[-1].group(1):
            continue
        out.append(m)
    return out


def _split_chapters_and_sections(
    full_text: str,
) -> list[tuple[str, str, str, str]]:
    """Split a Part's full text into (chapter_num, chapter_title,
    section_num, section_title, body) tuples — wait, that's five.

    Returns a flat list of (chapter, section, title, body). When a Part
    has no inner Chapter header (some smaller Parts like 5D are
    "Chapter-less" — straight to Sections), chapter_num is "".
    """
    # First split by chapter, then split each chapter into sections.
    # Dedupe before TOC-filter so a TOC-skipped chapter doesn't leave a
    # gap that lets the next body banner restart the same chapter number.
    chapter_matches = _dedupe_consecutive_same_number(
        list(_CHAPTER_HEADER.finditer(full_text))
    )

    if not chapter_matches:
        # No chapter headers — treat the whole thing as Chapter "" and
        # split into sections directly.
        return [
            ("", sec_num, sec_title, body)
            for sec_num, sec_title, body in _split_into_sections(full_text)
        ]

    out: list[tuple[str, str, str, str]] = []
    for i, m in enumerate(chapter_matches):
        ch_title = m.group(2).strip()
        if _TOC_LEADER.search(ch_title):
            continue  # TOC chapter listing — real banner appears later
        ch_num = m.group(1)
        start = m.end()
        end = chapter_matches[i + 1].start() if i + 1 < len(chapter_matches) else len(full_text)
        chapter_body = full_text[start:end]
        sections = _split_into_sections(chapter_body)
        if not sections:
            # Chapter exists but no section headers — emit the whole
            # chapter as one row.
            out.append((ch_num, "", ch_title, _clean_text(chapter_body)))
            continue
        for sec_num, sec_title, body in sections:
            out.append((ch_num, sec_num, ch_title + " — " + sec_title, body))
    return out


def _split_into_sections(chapter_body: str) -> list[tuple[str, str, str]]:
    """Inside a chapter, split on Section headers. Returns
    (section_num, section_title, body_text) tuples.

    Skips TOC false positives — lines like
    ``Section 3   Engineering Systems Overview...........5`` whose
    title group contains a leader-dot run. The same real section
    header appears later in the body without leader dots and lands
    in the output normally. Also dedupes running-header section
    banners (same section number repeating on every page).
    """
    matches = _dedupe_consecutive_same_number(
        list(_SECTION_HEADER.finditer(chapter_body))
    )
    if not matches:
        return []

    out: list[tuple[str, str, str]] = []
    for i, m in enumerate(matches):
        sec_title = m.group(2).strip()
        if _TOC_LEADER.search(sec_title):
            continue  # TOC entry — real section header arrives later
        sec_num = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(chapter_body)
        body = _clean_text(chapter_body[start:end])
        if body:
            out.append((sec_num, sec_title, body))
    return out


def _extract_text(pdf_path: Path) -> str:
    """Shell out to ``pdftotext`` for memory-light PDF text extraction.

    Mirrors uscg_msm.py — pdfplumber loaded the full ABS Pt.5C-2 (58 MB,
    ~2000 pages) into ~1 GB resident memory which thrashes our 1.5 GB
    cgroup cap. pdftotext is a streaming C utility from poppler-utils
    with a flat memory profile regardless of PDF size. The ABS rule
    text is paragraph-based (no critical table layout), so the layout
    fidelity loss is acceptable.
    """
    out = subprocess.check_output(
        ["pdftotext", str(pdf_path), "-"],
        text=True,
        stderr=subprocess.DEVNULL,
    )
    return out


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse every PDF in ``raw_dir`` into Section objects."""
    if not raw_dir.exists():
        raise FileNotFoundError(f"ABS raw directory not found: {raw_dir}")

    pdf_files = sorted(raw_dir.glob("*.pdf"))
    if not pdf_files:
        logger.warning("No PDF files found in %s", raw_dir)
        return []

    sections: list[Section] = []
    for pdf_path in pdf_files:
        part = _detect_part(pdf_path)
        logger.info("ABS MVR: parsing %s (Part %s)…", pdf_path.name, part)

        full_text = _extract_text(pdf_path)

        # Two of the auxiliary PDFs lack a proper chapter/section
        # hierarchy and the heuristic split produces garbage on them:
        #
        #   * Notations  — class-notations-table-jul25.pdf is a tabular
        #                  reference (notation → description).
        #   * Notices    — 1-mvr-nandgi-jul25.pdf is the "Notices and
        #                  General Information" change-summary doc;
        #                  the chapter headers it does have are
        #                  one-line entries with almost no body.
        #
        # Force the single-section fallback for both so they ingest
        # as one searchable bulk document each.
        if part in ("Notations", "Notices"):
            rows = []
        else:
            rows = _split_chapters_and_sections(full_text)
        if not rows:
            # No internal structure detected (e.g. Notices file is a
            # short summary table). Emit the whole document as one
            # section so the content is at least searchable.
            cleaned = _clean_text(full_text)
            if cleaned:
                section_number = f"ABS MVR Pt.{part}"
                sections.append(Section(
                    source=SOURCE,
                    title_number=TITLE_NUMBER,
                    section_number=section_number,
                    section_title=f"ABS Marine Vessel Rules — Part {part}"[:500],
                    full_text=cleaned,
                    up_to_date_as_of=SOURCE_DATE,
                    parent_section_number=None,
                ))
            continue

        for ch_num, sec_num, title, body in rows:
            if not body:
                continue
            if ch_num and sec_num:
                section_number = f"ABS MVR Pt.{part} Ch.{ch_num} Sec.{sec_num}"
            elif ch_num:
                section_number = f"ABS MVR Pt.{part} Ch.{ch_num}"
            elif sec_num:
                section_number = f"ABS MVR Pt.{part} Sec.{sec_num}"
            else:
                continue
            sections.append(Section(
                source=SOURCE,
                title_number=TITLE_NUMBER,
                section_number=section_number,
                section_title=title[:500],
                full_text=body,
                up_to_date_as_of=SOURCE_DATE,
                parent_section_number=f"ABS MVR Pt.{part}",
            ))

    logger.info(
        "ABS MVR: %d sections parsed across %d PDF files",
        len(sections), len(pdf_files),
    )
    return sections


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    """No-op: ABS MVR PDFs are pre-downloaded from ww2.eagle.org.

    The download itself runs out-of-band (see Sprint D6.93 notes —
    8 PDFs fetched via curl, ~217 MB). Parts 1/2/5A/5B/7 are deferred
    pending discovery of the correct filename convention. The CLI
    dispatcher expects this function; returning (file_count, 0) lets
    the dispatcher proceed to parse_source.
    """
    _ = failed_dir
    raw_dir.mkdir(parents=True, exist_ok=True)
    count = len(list(raw_dir.glob("*.pdf")))
    console.print(
        f"  [cyan]abs_mvr:[/cyan] {count} ABS MVR PDF files "
        f"(manually placed, no download)"
    )
    return count, 0


def get_source_date(raw_dir: Path) -> date:
    _ = raw_dir
    return SOURCE_DATE


def dry_run(raw_dir: Path) -> None:
    sections = parse_source(raw_dir)
    print(f"\nABS MVR: {len(sections)} sections parsed\n")
    for s in sections[:30]:
        preview = s.full_text[:80].replace("\n", " ")
        print(f"  [{s.section_number}]")
        print(f"    {s.section_title}")
        print(f"    {len(s.full_text):,} chars | {preview}...")
        print()
    if len(sections) > 30:
        print(f"  ... and {len(sections) - 30} more sections")

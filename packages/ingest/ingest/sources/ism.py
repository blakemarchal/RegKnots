"""
ISM Code (International Safety Management Code for the Safe Operation of Ships
and for Pollution Prevention) source adapter.

Two-phase pipeline (mirrors STCW):
  Phase 1 (--extract): Send page screenshots to Claude Vision for OCR.
  Phase 2 (--fresh):   Parse extracted .txt files into Section objects for
                       the standard chunking → embedding → pgvector pipeline.

Usage:
  # Phase 1 — extract text from images
  uv run python -m ingest.cli --source ism --extract

  # Phase 2 — ingest extracted text
  uv run python -m ingest.cli --source ism --fresh

  # Both phases in one command
  uv run python -m ingest.cli --source ism --extract --fresh

  # Standalone dry-run
  uv run python -m ingest.sources.ism --dry-run data/raw/ism/
"""

import argparse
import asyncio
import base64
import logging
import re
import sys
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "ism"
TITLE_NUMBER = 0
SOURCE_DATE = date(2018, 7, 1)        # 2018 consolidated edition (most recent)
UP_TO_DATE_AS_OF = date(2018, 7, 1)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

# ── Vision extraction prompt ─────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """\
You are a precise document OCR system extracting text from screenshots of the \
ISM Code (International Safety Management Code for the Safe Operation of Ships \
and for Pollution Prevention), an IMO publication.

EXTRACTION RULES:
1. Extract ALL text exactly as written, preserving the complete document structure.
2. Preserve all structural elements exactly:
   - Part headings (e.g., "PART A\\nIMPLEMENTATION", "PART B\\nCERTIFICATION AND VERIFICATION")
   - Numbered section headings (e.g., "1 General", "2 Safety and environmental-protection policy")
   - Sub-numbered headings (e.g., "1.1 Definitions", "1.2 Objectives", "1.2.1", "1.2.2")
   - Paragraph numbering (numbered and lettered sub-paragraphs)
   - Table content (preserve as plain text with clear column/row structure)
   - Footnotes with their reference marks (* \u2020 \u2021 or superscript numbers)
   - Resolution titles when present (e.g., "Resolution A.741(18)")
3. Insert a blank line before each major structural heading (Part, top-level numbered section).
4. For tables: use pipe-delimited format (| col1 | col2 | col3 |) with a header separator row.
5. Place each top-level numbered section ("1 General", "2 ...", etc.) on its own line \
with the number and title together: "1 General".

IGNORE completely (do not include in output):
- Any "INTERNATIONAL MARITIME ORGANIZATION" or IMO watermark
- Page numbers at page bottom
- "ISM CODE" or "ISM CODE 2018 EDITION" footer/header text
- Any sidebar tab text
- Any "Delivered by Base to:" watermark lines
- Any order/license numbers or timestamps

Output ONLY the clean extracted text. No commentary, no markdown code fences, \
no "Here is the extracted text:" preamble. Just the document text.\
"""

# ── Structure detection regexes ──────────────────────────────────────────────

# "PART A" or "PART A IMPLEMENTATION" — case-insensitive, optionally followed
# by a title on the same or next line.
_PART_RE = re.compile(
    r"^(PART\s+[AB])\b\s*(?:[—\-–:]?\s*)?(.*)$",
    re.MULTILINE,
)

# Top-level numbered sections: "1 General", "2 Safety and ...", up through 16.
# Anchored at start of line, followed by a single number (1-16), then a space
# and a title that does not start with another digit. Excludes sub-sections
# (which have a dot) so "1.1" doesn't false-positive here.
_SECTION_RE = re.compile(
    r"^(\d{1,2})\s+([A-Z][^\n\d][^\n]{2,})$",
    re.MULTILINE,
)

# Sub-sections like "1.1 Definitions", "1.2.1 ..."
# Must start at line beginning with N.N or N.N.N pattern, then a title.
_SUBSECTION_RE = re.compile(
    r"^(\d{1,2}(?:\.\d{1,2}){1,2})\s+([A-Z][^\n]{2,})$",
    re.MULTILINE,
)


# ── Text cleaning ────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Remove residual OCR artifacts from Vision-extracted ISM text."""
    # 1. Strip null bytes
    text = text.replace("\x00", "")
    # 2. Remove residual watermark fragments Vision may have partially captured
    text = re.sub(r"(?i)\b(?:INTER(?:NATIONAL)?|MARITIME|ORGANI[ZS]ATION)\b", "", text)
    # 3. Remove delivery/license watermark lines
    text = re.sub(r"^.*(?:Delivered by|Base to:).*$", "", text, flags=re.MULTILINE)
    # 4. Remove order number lines
    text = re.sub(
        r"^\s*(?:[A-Z0-9]{5,10}|[A-Z]{1,3}:[A-Z]\s*[A-Z]?)\s*$", "",
        text, flags=re.MULTILINE,
    )
    # 5. Remove ISM Code page footers
    text = re.sub(
        r"(?i)^.*ISM\s+CODE(?:\s+\d{4}\s+EDITION)?.*$", "",
        text, flags=re.MULTILINE,
    )
    text = re.sub(r"^\s*\d{1,4}\s*$", "", text, flags=re.MULTILINE)  # bare page numbers
    # 6. Collapse 3+ blank lines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    # 7. Strip
    return text.strip()


# ── Phase 1: Vision extraction ───────────────────────────────────────────────

async def extract_images(raw_dir: Path, force: bool = False) -> None:
    """Run Claude Vision extraction on all screenshot images.

    Args:
        raw_dir: Path to data/raw/ism/ — must contain .png/.jpg files.
        force:   If True, re-extract even if .txt already exists.
    """
    from anthropic import AsyncAnthropic
    from ingest.config import settings

    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    # Collect and sort images alphabetically by filename.
    # Filenames should sort in page order (e.g., timestamps or zero-padded indices).
    images = sorted(
        [f for f in raw_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTS],
        key=lambda f: f.name,
    )
    if not images:
        print(f"ERROR: No images found in {raw_dir}", file=sys.stderr)
        sys.exit(1)

    extracted_dir = raw_dir / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)

    print(f"Found {len(images)} images in {raw_dir}")

    # Build pairs for Vision calls (two pages per call to keep token use sane)
    pairs: list[list[Path]] = []
    for i in range(0, len(images), 2):
        pair = [images[i]]
        if i + 1 < len(images):
            pair.append(images[i + 1])
        pairs.append(pair)

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    skipped = 0
    extracted = 0

    for batch_idx, pair in enumerate(pairs):
        # Use the full image stem as the page identifier (filenames may be
        # arbitrary). Extracted .txt files mirror image stems 1:1.
        page_nums = [f.stem for f in pair]

        # Check if all pages in this pair already have .txt
        out_paths = [extracted_dir / f"{pn}.txt" for pn in page_nums]
        if not force and all(p.exists() for p in out_paths):
            skipped += len(pair)
            continue

        label = "-".join(page_nums)
        print(
            f"  Extracting pages {label}... "
            f"({batch_idx + 1}/{len(pairs)})"
        )

        # Build message content with images
        content: list[dict] = []
        for img_path in pair:
            img_bytes = img_path.read_bytes()
            b64 = base64.b64encode(img_bytes).decode("utf-8")
            suffix = img_path.suffix.lower()
            media_type = "image/png" if suffix == ".png" else "image/jpeg"
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64,
                },
            })

        content.append({
            "type": "text",
            "text": "Extract all text from the page(s) above following the extraction rules.",
        })

        try:
            resp = await client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=8192,
                system=_VISION_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
            )
            raw_text = resp.content[0].text if resp.content else ""
        except Exception as exc:
            print(f"    ERROR extracting pages {label}: {exc}", file=sys.stderr)
            continue

        cleaned = _clean_text(raw_text)

        # If single page, write to one file. If pair, split roughly in half.
        if len(pair) == 1:
            out_paths[0].write_text(cleaned, encoding="utf-8")
            extracted += 1
        else:
            lines = cleaned.split("\n")
            mid = len(lines) // 2
            first_half = "\n".join(lines[:mid]).strip()
            second_half = "\n".join(lines[mid:]).strip()

            if first_half:
                out_paths[0].write_text(first_half, encoding="utf-8")
            if second_half:
                out_paths[1].write_text(second_half, encoding="utf-8")
            extracted += 2

        # Rate limiting
        await asyncio.sleep(1.0)

    print(f"\nExtraction complete: {extracted} pages extracted, {skipped} skipped")


# ── Phase 2: Parse extracted text into sections ──────────────────────────────

def parse_source(raw_dir: Path) -> list[Section]:
    """Parse extracted ISM text files into Section objects.

    Args:
        raw_dir: Path to data/raw/ism/extracted/ — must contain .txt files.
    Returns:
        List of Section objects ordered by page sequence.
    """
    txt_files = sorted(
        [f for f in raw_dir.iterdir() if f.suffix == ".txt"],
        key=lambda f: f.name,
    )
    if not txt_files:
        raise ValueError(
            f"No .txt files found in {raw_dir}. "
            "Run --extract first to generate them from page images."
        )

    # Concatenate all pages
    full_text = ""
    for txt_path in txt_files:
        page_text = txt_path.read_text(encoding="utf-8", errors="replace")
        full_text += page_text + "\n\n"

    # Detect and skip table of contents pages
    full_text = _skip_toc(full_text)

    # Find all structural boundaries
    boundaries = _find_boundaries(full_text)

    if not boundaries:
        logger.warning("ism: No structural boundaries found — creating single section")
        return [Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number="ISM Code",
            section_title="ISM Code — Full Text",
            full_text=full_text.strip(),
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number=None,
        )]

    sections: list[Section] = []

    # Content before first boundary = preamble
    first_pos = boundaries[0][0]
    preamble = full_text[:first_pos].strip()
    if preamble and len(preamble) > 50:
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number="ISM Preamble",
            section_title="Preamble",
            full_text=preamble,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number="ISM Code",
        ))

    # Build sections from boundaries
    for i, (pos, heading_type, heading_raw, title) in enumerate(boundaries):
        end_pos = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(full_text)
        section_text = full_text[pos:end_pos].strip()

        sec_num = _format_section_number(heading_type, heading_raw)
        parent = _format_parent(heading_type, heading_raw)

        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=sec_num,
            section_title=title.strip() or sec_num,
            full_text=section_text,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number=parent,
        ))

    logger.info(
        "ism: %d txt files -> %d sections",
        len(txt_files), len(sections),
    )
    return sections


def _skip_toc(text: str) -> str:
    """Detect and remove table of contents pages from the beginning of text."""
    lines = text.split("\n")
    # TOC heuristic: many lines with "Section" + page numbers in first ~200 lines
    toc_end = 0
    toc_ref_count = 0
    for i, line in enumerate(lines[:200]):
        stripped = line.strip()
        # Lines like "1 General .................. 5" or "Part A ........... 3"
        if re.match(r"^(?:Part|Section|\d{1,2}(?:\.\d{1,2})?)\s+.*\d{1,3}\s*$", stripped):
            toc_ref_count += 1
            toc_end = i

    if toc_ref_count >= 8:
        skip_to = min(toc_end + 5, len(lines))
        logger.info("ism: Skipping TOC pages (first ~%d lines)", skip_to)
        return "\n".join(lines[skip_to:])

    return text


def _find_boundaries(text: str) -> list[tuple[int, str, str, str]]:
    """Find all structural boundaries in the text.

    Returns list of (position, type, raw_heading, title) tuples, sorted by position.
    """
    boundaries: list[tuple[int, str, str, str]] = []

    for m in _PART_RE.finditer(text):
        boundaries.append((m.start(), "part", m.group(1).strip(), m.group(2).strip()))

    for m in _SECTION_RE.finditer(text):
        num = m.group(1)
        # Only accept top-level section numbers 1-16 (ISM has 16 numbered sections)
        if num.isdigit() and 1 <= int(num) <= 16:
            boundaries.append((m.start(), "section", num, m.group(2).strip()))

    for m in _SUBSECTION_RE.finditer(text):
        boundaries.append((m.start(), "subsection", m.group(1), m.group(2).strip()))

    # Sort by position in text, then deduplicate overlapping starts (prefer
    # the more specific subsection over a section that happens to start at
    # the same byte offset).
    boundaries.sort(key=lambda b: (b[0], 0 if b[1] == "subsection" else 1))

    deduped: list[tuple[int, str, str, str]] = []
    seen_positions: set[int] = set()
    for b in boundaries:
        if b[0] in seen_positions:
            continue
        seen_positions.add(b[0])
        deduped.append(b)

    return deduped


def _format_section_number(heading_type: str, raw: str) -> str:
    """Convert a heading into a canonical section_number."""
    raw_stripped = raw.strip()

    if heading_type == "part":
        # "PART A" -> "ISM Part A"
        letter = re.sub(r"^PART\s+", "", raw_stripped, flags=re.IGNORECASE)
        return f"ISM Part {letter}"

    if heading_type == "section":
        # "1" -> "ISM 1"
        return f"ISM {raw_stripped}"

    if heading_type == "subsection":
        # "1.2.1" -> "ISM 1.2.1"
        return f"ISM {raw_stripped}"

    return f"ISM {raw_stripped}"


def _format_parent(heading_type: str, raw: str) -> str:
    """Determine the parent_section_number for a heading."""
    raw_stripped = raw.strip()

    if heading_type == "part":
        return "ISM Code"

    if heading_type == "section":
        # Section 1-12 -> Part A, Section 13-16 -> Part B
        try:
            n = int(raw_stripped)
            if 1 <= n <= 12:
                return "ISM Part A"
            if 13 <= n <= 16:
                return "ISM Part B"
        except ValueError:
            pass
        return "ISM Code"

    if heading_type == "subsection":
        # "1.2.1" -> parent is "ISM 1.2"; "1.2" -> parent is "ISM 1"
        parts = raw_stripped.split(".")
        if len(parts) >= 2:
            parent_num = ".".join(parts[:-1])
            return f"ISM {parent_num}"
        return "ISM Code"

    return "ISM Code"


# ── Dry-run ──────────────────────────────────────────────────────────────────

def dry_run(raw_dir: Path) -> None:
    """Print detected sections from extracted text and exit."""
    # If raw_dir itself contains .txt files, use it; otherwise look in extracted/
    if raw_dir.name != "extracted" and (raw_dir / "extracted").exists():
        extracted_dir = raw_dir / "extracted"
    else:
        extracted_dir = raw_dir

    txt_files = [f for f in extracted_dir.iterdir() if f.suffix == ".txt"]
    if not txt_files:
        print(f"ERROR: No .txt files found in {extracted_dir}", file=sys.stderr)
        print("Run --extract first to generate them from page images.", file=sys.stderr)
        sys.exit(1)

    try:
        sections = parse_source(extracted_dir)
    except ValueError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"\nISM: {len(sections)} sections detected\n")
    for s in sections:
        text_preview = s.full_text[:80].replace("\n", " ")
        print(f"  [{s.section_number}]")
        print(f"    Title:  {s.section_title}")
        print(f"    Parent: {s.parent_section_number}")
        print(f"    {len(s.full_text):,} chars | {text_preview}...")
        print()


# ── CLI entry point ──────────────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="ISM Code ingest adapter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract text from page images
  uv run python -m ingest.sources.ism --extract data/raw/ism/

  # Verify structure detection
  uv run python -m ingest.sources.ism --dry-run data/raw/ism/

  # Force re-extraction
  uv run python -m ingest.sources.ism --extract data/raw/ism/ --force
        """,
    )
    parser.add_argument(
        "--extract",
        metavar="RAW_DIR",
        help="Run Vision extraction on images in RAW_DIR",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract even if .txt files exist",
    )
    parser.add_argument(
        "--dry-run",
        metavar="RAW_DIR",
        help="Print detected section structure and exit",
    )

    args = parser.parse_args()

    if args.extract:
        asyncio.run(extract_images(Path(args.extract), force=args.force))
    elif args.dry_run:
        dry_run(Path(args.dry_run))
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()

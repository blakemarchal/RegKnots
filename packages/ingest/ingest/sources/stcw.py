"""
STCW Convention (International Convention on Standards of Training, Certification
and Watchkeeping for Seafarers, 1978, as amended — Consolidated Edition 2017)
source adapter.

Two-phase pipeline:
  Phase 1 (--extract): Send page screenshots to Claude Vision for OCR.
  Phase 2 (--fresh):   Parse extracted .txt files into Section objects for
                       the standard chunking → embedding → pgvector pipeline.

Usage:
  # Phase 1 — extract text from images
  uv run python -m ingest.cli --source stcw --extract

  # Phase 2 — ingest extracted text
  uv run python -m ingest.cli --source stcw --fresh

  # Both phases in one command
  uv run python -m ingest.cli --source stcw --extract --fresh

  # Standalone dry-run
  uv run python -m ingest.sources.stcw --dry-run data/raw/stcw/
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

SOURCE = "stcw"
TITLE_NUMBER = 0
SOURCE_DATE = date(2017, 7, 1)       # STCW Consolidated Edition 2017
UP_TO_DATE_AS_OF = date(2017, 7, 1)

_IMAGE_EXTS = {".png", ".jpg", ".jpeg"}

# ── Vision extraction prompt ─────────────────────────────────────────────────

_VISION_SYSTEM_PROMPT = """\
You are a precise document OCR system extracting text from screenshots of the \
STCW Convention (International Convention on Standards of Training, Certification \
and Watchkeeping for Seafarers, 1978, as amended).

EXTRACTION RULES:
1. Extract ALL text exactly as written, preserving the complete document structure.
2. Preserve all structural elements exactly:
   - Article numbers and titles (e.g., "Article I\\nGeneral obligations under the Convention")
   - Chapter headings (e.g., "Chapter II\\nMaster and deck department")
   - Regulation numbers and titles (e.g., "Regulation II/1\\nMandatory minimum requirements...")
   - STCW Code section references (e.g., "Section A-II/1", "Section B-II/1")
   - Paragraph numbering (1, 2, 3... and .1, .2, .3... sub-paragraphs)
   - Table content (preserve as plain text with clear column/row structure)
   - Footnotes with their reference marks (* \u2020 \u2021 or superscript numbers)
   - Resolution titles (e.g., "Resolution 1\\nAdoption of amendments...")
3. Insert a blank line before each major structural heading (Article, Chapter, Regulation, Section).
4. For tables: use pipe-delimited format (| col1 | col2 | col3 |) with a header separator row.

IGNORE completely (do not include in output):
- The diagonal "INTERNATIONAL MARITIME ORGANIZATION" watermark
- Page numbers at page bottom
- "STCW CONSOLIDATED EDITION 2017" footer/header text
- "STCW CONVENTION" or "STCW CODE" sidebar tab text
- Any "Delivered by Base to:" watermark lines
- Any order/license numbers or timestamps

Output ONLY the clean extracted text. No commentary, no markdown code fences, \
no "Here is the extracted text:" preamble. Just the document text.\
"""

# ── Structure detection regexes ──────────────────────────────────────────────

_ARTICLE_RE = re.compile(
    r"^(Article\s+[IVXLC]+(?:\s*\([a-z]\))?)\s*\n(.+)",
    re.MULTILINE,
)
_CHAPTER_RE = re.compile(
    r"^(Chapter\s+[IVXLC]+(?:-\d)?)\s*\n(.+)",
    re.MULTILINE,
)
_REGULATION_RE = re.compile(
    r"^(Regulation\s+[IVXLC]+(?:-\d)?/\d+(?:\.\d+)?)\s*\n(.+)",
    re.MULTILINE,
)
_CODE_SECTION_RE = re.compile(
    r"^(Section\s+[AB]-[IVXLC]+(?:-\d)?/\d+(?:\.\d+)?)\s*\n(.+)",
    re.MULTILINE,
)
_RESOLUTION_RE = re.compile(
    r"^(Resolution\s+\d+)\s*\n(.+)",
    re.MULTILINE,
)
_PART_RE = re.compile(
    r"^(Part\s+[A-Z](?:-[IVXLC]+)?)\s*\n(.+)",
    re.MULTILINE,
)


# ── Text cleaning ────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Remove residual OCR artifacts from Vision-extracted STCW text."""
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
    # 5. Remove page footers
    text = re.sub(
        r"(?i)^.*STCW\s+CONSOLIDATED\s+EDITION\s+2017.*$", "",
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
        raw_dir: Path to data/raw/stcw/ — must contain .png/.jpg files.
        force:   If True, re-extract even if .txt already exists.
    """
    from anthropic import AsyncAnthropic
    from ingest.config import settings

    if not settings.anthropic_api_key:
        print("ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)

    # Collect and sort images alphabetically by filename.
    # Windows Game Bar timestamps in filenames preserve chronological/page order.
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

    # Build pairs for Vision calls
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
        # arbitrary, e.g. Windows Game Bar timestamps). Extracted .txt files
        # mirror image stems 1:1.
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

        # If single page, write to one file. If pair, split roughly in half
        # by looking for a large gap or just write the whole thing to each page
        if len(pair) == 1:
            out_paths[0].write_text(cleaned, encoding="utf-8")
            extracted += 1
        else:
            # Write entire extracted text to both page files
            # (the Vision model sees both pages together and extracts sequentially)
            # Split by finding a natural midpoint
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
    """Parse extracted STCW text files into Section objects.

    Args:
        raw_dir: Path to data/raw/stcw/extracted/ — must contain .txt files.
    Returns:
        List of Section objects ordered by page sequence.
    """
    # Sort alphabetically — .txt filenames mirror source image stems, which
    # are chronologically ordered (Windows Game Bar timestamps).
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
        logger.warning("stcw: No structural boundaries found — creating single section")
        return [Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number="STCW Convention",
            section_title="STCW Convention — Full Text",
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
            section_number="STCW Preamble",
            section_title="Preamble",
            full_text=preamble,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number="STCW Convention",
        ))

    # Build sections from boundaries
    for i, (pos, heading_type, heading_raw, title) in enumerate(boundaries):
        # Section text runs from this boundary to the next
        end_pos = boundaries[i + 1][0] if i + 1 < len(boundaries) else len(full_text)
        section_text = full_text[pos:end_pos].strip()

        sec_num = _format_section_number(heading_type, heading_raw)
        parent = _format_parent(heading_type, heading_raw)

        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=sec_num,
            section_title=title.strip(),
            full_text=section_text,
            up_to_date_as_of=UP_TO_DATE_AS_OF,
            parent_section_number=parent,
        ))

    logger.info(
        "stcw: %d txt files -> %d sections",
        len(txt_files), len(sections),
    )
    return sections


def _skip_toc(text: str) -> str:
    """Detect and remove table of contents pages from the beginning of text."""
    lines = text.split("\n")
    # TOC heuristic: many lines with "Chapter" + page numbers in first ~200 lines
    toc_end = 0
    chapter_ref_count = 0
    for i, line in enumerate(lines[:200]):
        stripped = line.strip()
        # Lines like "Chapter II  Master and deck department ........... 45"
        if re.match(r"^(?:Chapter|Part|Section|Article|Annex)\s+.*\d{1,3}\s*$", stripped):
            chapter_ref_count += 1
            toc_end = i

    if chapter_ref_count >= 8:
        # Skip everything up to the last TOC-like line + a few lines
        skip_to = min(toc_end + 5, len(lines))
        logger.info("stcw: Skipping TOC pages (first ~%d lines)", skip_to)
        return "\n".join(lines[skip_to:])

    return text


def _find_boundaries(text: str) -> list[tuple[int, str, str, str]]:
    """Find all structural boundaries in the text.

    Returns list of (position, type, raw_heading, title) tuples, sorted by position.
    """
    boundaries: list[tuple[int, str, str, str]] = []

    for m in _ARTICLE_RE.finditer(text):
        boundaries.append((m.start(), "article", m.group(1), m.group(2)))

    for m in _CHAPTER_RE.finditer(text):
        boundaries.append((m.start(), "chapter", m.group(1), m.group(2)))

    for m in _REGULATION_RE.finditer(text):
        boundaries.append((m.start(), "regulation", m.group(1), m.group(2)))

    for m in _CODE_SECTION_RE.finditer(text):
        boundaries.append((m.start(), "code_section", m.group(1), m.group(2)))

    for m in _RESOLUTION_RE.finditer(text):
        boundaries.append((m.start(), "resolution", m.group(1), m.group(2)))

    for m in _PART_RE.finditer(text):
        boundaries.append((m.start(), "part", m.group(1), m.group(2)))

    # Sort by position in text
    boundaries.sort(key=lambda b: b[0])
    return boundaries


def _format_section_number(heading_type: str, raw: str) -> str:
    """Convert a heading into a canonical section_number."""
    raw_stripped = raw.strip()

    if heading_type == "article":
        # "Article I" -> "STCW Article I"
        num = re.sub(r"^Article\s+", "", raw_stripped, flags=re.IGNORECASE)
        return f"STCW Article {num}"

    if heading_type == "chapter":
        # "Chapter II" -> "STCW Ch.II"
        num = re.sub(r"^Chapter\s+", "", raw_stripped, flags=re.IGNORECASE)
        return f"STCW Ch.{num}"

    if heading_type == "regulation":
        # "Regulation II/1" -> "STCW Ch.II Reg.II/1"
        num = re.sub(r"^Regulation\s+", "", raw_stripped, flags=re.IGNORECASE)
        # Extract chapter from regulation number (e.g., "II" from "II/1")
        ch_match = re.match(r"([IVXLC]+(?:-\d)?)/", num)
        ch = ch_match.group(1) if ch_match else ""
        return f"STCW Ch.{ch} Reg.{num}" if ch else f"STCW Reg.{num}"

    if heading_type == "code_section":
        # "Section A-II/1" -> "STCW Code A-II/1"
        num = re.sub(r"^Section\s+", "", raw_stripped, flags=re.IGNORECASE)
        return f"STCW Code {num}"

    if heading_type == "resolution":
        # "Resolution 1" -> "STCW Resolution 1"
        num = re.sub(r"^Resolution\s+", "", raw_stripped, flags=re.IGNORECASE)
        return f"STCW Resolution {num}"

    if heading_type == "part":
        # "Part A" -> "STCW Code Part A"
        num = re.sub(r"^Part\s+", "", raw_stripped, flags=re.IGNORECASE)
        return f"STCW Code Part {num}"

    return f"STCW {raw_stripped}"


def _format_parent(heading_type: str, raw: str) -> str:
    """Determine the parent_section_number for a heading."""
    raw_stripped = raw.strip()

    if heading_type == "article":
        return "STCW Convention"

    if heading_type == "chapter":
        return "STCW Convention"

    if heading_type == "regulation":
        # Parent is the chapter: "Regulation II/1" -> "STCW Ch.II"
        num = re.sub(r"^Regulation\s+", "", raw_stripped, flags=re.IGNORECASE)
        ch_match = re.match(r"([IVXLC]+(?:-\d)?)/", num)
        if ch_match:
            return f"STCW Ch.{ch_match.group(1)}"
        return "STCW Convention"

    if heading_type == "code_section":
        # "Section A-II/1" -> parent is "STCW Code Part A"
        num = re.sub(r"^Section\s+", "", raw_stripped, flags=re.IGNORECASE)
        part_match = re.match(r"([AB])-", num)
        if part_match:
            return f"STCW Code Part {part_match.group(1)}"
        return "STCW Code"

    if heading_type == "resolution":
        return "STCW Resolutions"

    if heading_type == "part":
        return "STCW Code"

    return "STCW Convention"


# ── Dry-run ──────────────────────────────────────────────────────────────────

def dry_run(raw_dir: Path) -> None:
    """Print detected sections from extracted text and exit."""
    extracted_dir = raw_dir / "extracted" if not (raw_dir / "extracted").name == "extracted" else raw_dir
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

    print(f"\nSTCW: {len(sections)} sections detected\n")
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
        description="STCW ingest adapter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Extract text from page images
  uv run python -m ingest.sources.stcw --extract data/raw/stcw/

  # Verify structure detection
  uv run python -m ingest.sources.stcw --dry-run data/raw/stcw/

  # Force re-extraction
  uv run python -m ingest.sources.stcw --extract data/raw/stcw/ --force
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

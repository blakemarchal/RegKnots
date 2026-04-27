"""
IMDG Code (International Maritime Dangerous Goods Code) source adapter.

Sprint D6.12 — ingests the IMDG Code Volume 1 + Volume 2, 2024 Edition
(Amendment 42-24). Mandatory under SOLAS Chapter VII Regulation 1.4 for
the carriage of dangerous goods in packaged form by sea.

Mirrors the SOLAS / MARPOL adapter pattern. The text is produced
upstream by:
  scripts/ocr_imdg_screenshots.py     OCR via Claude Sonnet 4.6 Vision
  scripts/consolidate_imdg_pages.py   Stitch transcripts → section files

Input layout — data/raw/imdg/
  headers.txt            — one line per page range: "START-END: TITLE"
                           comments start with '#', blank lines ignored.
  <start>-<end>.txt      — consolidated text for those pages, e.g. "41-50.txt"
  extracted/             — internal artifacts (raw OCR cache + pagemap),
                           NOT read by this adapter.

Section number canonical forms:
  "IMDG Part 1"          (umbrella for Part 1 sections, used as parent)
  "IMDG 1.1"             (Chapter 1.1 — General provisions)
  "IMDG 2.1"             (Chapter 2.1 — Class 1: Explosives)
  "IMDG 3.2"             (Chapter 3.2 — Dangerous Goods List)
  "IMDG 4.1"             (Chapter 4.1 — Packaging general)
  "IMDG 7.5"             (Chapter 7.5 — Stowage and segregation)
  "IMDG App.A"           (Appendix A)
  "IMDG Index"           (Alphabetical Index)
  "IMDG Foreword"        (Foreword / preamble)

Parent section number routing:
  Chapter X.Y → "IMDG Part X"
  Appendices / Index / Foreword → "IMDG"

Dry-run mode (no DB/API calls):
  uv run python -m ingest.sources.imdg --dry-run data/raw/imdg/
"""

import argparse
import logging
import re
import sys
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "imdg"
TITLE_NUMBER = 0

# IMDG Code Amendment 42-24 — adopted by Resolution MSC.521(106) and
# entered into force voluntarily 1 January 2025, mandatory 1 January
# 2026. The 2024 Edition is the consolidated print of the Code as
# amended through 42-24.
SOURCE_DATE      = date(2024, 7, 1)
UP_TO_DATE_AS_OF = date(2026, 1, 1)


# ── Regexes ───────────────────────────────────────────────────────────────────

_FILE_RANGE  = re.compile(r"^(\d+)-(\d+)\.txt$")
_HEADER_LINE = re.compile(r"^(\d+)-(\d+)\s*:\s*(.+)$")

_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)

# Running headers/footers of the IMDG Code 2024 layout.
_HEADER_FOOTER_PATTERNS = [
    re.compile(r"(?im)^.*IMDG\s+CODE.*(?:VOLUME\s+[12]|2024\s+EDITION).*$"),
    re.compile(r"(?im)^.*INCORPORATING\s+AMENDMENT\s+\d{2}-\d{2}.*$"),
    # Standalone numeric page footers
    re.compile(r"(?m)^\s*\d{1,4}\s*$"),
]

_DASH_LINE = re.compile(r"^[\-–—]{4,}\s*$", re.MULTILINE)

_PAGE_MARKER_LINE = re.compile(
    r"(?im)^===\s*(?:Left page|Right page|Book p\.|Page)?\s*"
    r"(?:\(book p\.|book p\.|p\.)?\s*[\w\d?]+\)?\s*===\s*$"
)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_source(raw_dir: Path) -> list[Section]:
    headers_path = raw_dir / "headers.txt"
    if not headers_path.exists():
        raise FileNotFoundError(
            f"headers.txt not found at {headers_path}. "
            "Create it with lines like: '45-78: Part 2 Chapter 2.1 — Class 1 Explosives'"
        )

    section_map = _parse_headers(headers_path)
    if not section_map:
        raise ValueError(f"headers.txt at {headers_path} contains no valid entries.")

    txt_files = sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )
    if not txt_files:
        raise ValueError(
            f"No <start>-<end>.txt files found in {raw_dir}. "
            "Run scripts/consolidate_imdg_pages.py --write-sections first."
        )

    sections: list[Section] = []
    unmatched: list[str] = []

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m
        key = (int(m.group(1)), int(m.group(2)))

        meta = section_map.get(key)
        if meta is None:
            logger.warning("imdg: no header entry for %s — skipping", txt_path.name)
            unmatched.append(txt_path.name)
            continue

        raw_text = txt_path.read_text(encoding="utf-8", errors="replace")
        text = _clean_text(raw_text)
        if not text:
            logger.warning("imdg: %s is empty after cleaning — skipping", txt_path.name)
            continue

        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = meta["section_number"],
            section_title         = meta["section_title"],
            full_text             = text,
            up_to_date_as_of      = UP_TO_DATE_AS_OF,
            parent_section_number = meta["parent_section_number"],
        ))

    if unmatched:
        logger.warning(
            "imdg: %d file(s) had no header entry: %s",
            len(unmatched), ", ".join(unmatched),
        )

    logger.info(
        "imdg: %d txt files → %d sections (%d unmatched)",
        len(txt_files), len(sections), len(unmatched),
    )
    return sections


def dry_run(raw_dir: Path) -> None:
    headers_path = raw_dir / "headers.txt"
    if not headers_path.exists():
        print(f"ERROR: headers.txt not found at {headers_path}", file=sys.stderr)
        sys.exit(1)

    section_map = _parse_headers(headers_path)
    if not section_map:
        print("ERROR: headers.txt contains no valid entries.", file=sys.stderr)
        sys.exit(1)

    txt_files = sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )

    matched   = 0
    unmatched = 0

    col_w = 14
    print(f"\n{'Pages':<{col_w}}  {'Matched':<8}  {'section_number':<22}  section_title")
    print("-" * 120)

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m
        key  = (int(m.group(1)), int(m.group(2)))
        meta = section_map.get(key)
        if meta:
            matched += 1
            print(
                f"{txt_path.name:<{col_w}}  {'✓':<8}  "
                f"{meta['section_number']:<22}  {meta['section_title']}"
            )
        else:
            unmatched += 1
            print(f"{txt_path.name:<{col_w}}  {'✗ NO MATCH':<8}")

    covered = {
        (int(_FILE_RANGE.match(p.name).group(1)), int(_FILE_RANGE.match(p.name).group(2)))  # type: ignore[union-attr]
        for p in txt_files
    }
    orphan_headers = [k for k in section_map if k not in covered]

    print("-" * 120)
    print(
        f"\nSummary: {len(txt_files)} txt files, "
        f"{matched} matched, {unmatched} unmatched, "
        f"{len(orphan_headers)} header entries with no txt file."
    )

    if orphan_headers:
        print("\nHeader entries with no txt file:")
        for k in sorted(orphan_headers):
            meta = section_map[k]
            print(f"  {k[0]}-{k[1]}: {meta['section_number']} — {meta['section_title']}")

    if unmatched or orphan_headers:
        sys.exit(1)
    else:
        print("\nAll files matched. ✓")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _parse_headers(headers_path: Path) -> dict[tuple[int, int], dict]:
    result: dict[tuple[int, int], dict] = {}

    for lineno, raw_line in enumerate(headers_path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        m = _HEADER_LINE.match(line)
        if not m:
            logger.warning("headers.txt line %d: unrecognised format — %r", lineno, line)
            continue

        start, end = int(m.group(1)), int(m.group(2))
        raw_title  = m.group(3).strip()

        sec_num   = _format_section_number(raw_title)
        sec_title = _format_section_title(raw_title)
        parent    = _format_parent(raw_title)

        result[(start, end)] = {
            "section_number":        sec_num,
            "section_title":         sec_title,
            "parent_section_number": parent,
        }

    return result


# ── Section number / title formatters ─────────────────────────────────────────
#
# Recognised header forms (before description suffix):
#   "Foreword"
#   "Part 1 Chapter 1.1"        → IMDG 1.1
#   "Part 2 Chapter 2.1"        → IMDG 2.1
#   "Chapter 3.2"               → IMDG 3.2  (when Part is omitted)
#   "Appendix A"                → IMDG App.A
#   "Index"                     → IMDG Index
#
# Multi-volume note: the IMDG Code is published as Vol 1 + Vol 2, but
# chapter numbering is continuous (Vol 2 contains Chapter 3.X — DGL +
# special provisions). Parent grouping follows Part number (1-7) so the
# physical volume split is invisible at the section_number level.

_RE_DESC_SUFFIX = re.compile(r"\s*[\-–—].*$")

_RE_FOREWORD = re.compile(r"^foreword\s*$", re.IGNORECASE)
_RE_INDEX = re.compile(r"^(?:alphabetical\s+)?index\s*$", re.IGNORECASE)
_RE_APPENDIX = re.compile(
    r"^appendix\s+([A-Z]|\d+)\s*$",
    re.IGNORECASE,
)

# "Part 1 Chapter 1.1" → ("1", "1.1")
# "Chapter 1.1"        → (None, "1.1")
# "Part 1"             → ("1", None)
_RE_PART_CHAPTER = re.compile(
    r"^(?:Part\s+(\d+))?\s*(?:Chapter\s+(\d+(?:\.\d+)?))?\s*$",
    re.IGNORECASE,
)


def _structural_part(raw: str) -> str:
    return _RE_DESC_SUFFIX.sub("", raw).strip()


def _format_section_number(raw: str) -> str:
    struct = _structural_part(raw)

    if _RE_FOREWORD.match(struct):
        return "IMDG Foreword"

    if _RE_INDEX.match(struct):
        return "IMDG Index"

    m = _RE_APPENDIX.match(struct)
    if m:
        return f"IMDG App.{m.group(1).upper()}"

    m = _RE_PART_CHAPTER.match(struct)
    if m:
        part_num = m.group(1)
        chapter = m.group(2)
        if chapter:
            return f"IMDG {chapter}"
        if part_num:
            return f"IMDG Part {part_num}"

    # Fallback — prefix with IMDG and use whatever the structural part was.
    return f"IMDG {struct.strip()}"


def _format_section_title(raw: str) -> str:
    return raw.strip().lstrip("–—-").strip()


def _format_parent(raw: str) -> str:
    struct = _structural_part(raw)

    if (
        _RE_FOREWORD.match(struct)
        or _RE_INDEX.match(struct)
        or _RE_APPENDIX.match(struct)
    ):
        return "IMDG"

    m = _RE_PART_CHAPTER.match(struct)
    if m:
        part_num = m.group(1)
        chapter = m.group(2)
        # "Chapter X.Y" → parent is the Part inferred from the chapter prefix
        if chapter:
            part_inferred = chapter.split(".")[0]
            return f"IMDG Part {part_inferred}"
        if part_num:
            return "IMDG"

    return "IMDG"


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _PAGE_MARKER_LINE.sub("", text)
    for rx in _HEADER_FOOTER_PATTERNS:
        text = rx.sub("", text)
    text = _DASH_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── CLI entry point (dry-run) ─────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="IMDG ingest adapter — dry-run mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  uv run python -m ingest.sources.imdg --dry-run data/raw/imdg/
        """,
    )
    parser.add_argument(
        "--dry-run",
        metavar="RAW_DIR",
        help="Print page-range → section mapping and exit.",
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run(Path(args.dry_run))
    else:
        parser.print_help()
        sys.exit(0)


if __name__ == "__main__":
    _main()

"""
SOLAS (International Convention for the Safety of Life at Sea) source adapter.

Input layout — data/raw/solas/
  headers.txt        — one line per page range: "START-END: TITLE"
                       comments start with '#', blank lines ignored.
  <start>-<end>.txt  — pre-extracted text for those pages (e.g. "5-12.txt").

Section number format:
  "SOLAS Articles"
  "SOLAS Ch.I Part A"          (Chapter I, Part A)
  "SOLAS Ch.II-1 Part B-1"     (Chapter II-1, Part B-1)
  "SOLAS Annex I"
  "SOLAS Appendix"

Parent section number:
  "SOLAS Articles"       → parent = "SOLAS"
  "SOLAS Ch.I Part A"    → parent = "SOLAS Ch.I"
  "SOLAS Annex I"        → parent = "SOLAS Annexes"
  "SOLAS Appendix"       → parent = "SOLAS"

Dry-run mode (no DB/API calls):
  uv run python -m ingest.sources.solas --dry-run data/raw/solas/
"""

import argparse
import logging
import re
import sys
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE        = "solas"
TITLE_NUMBER  = 0

# SOLAS Consolidated Edition 2024 (amendments up to MSC.507(105))
SOURCE_DATE      = date(2024, 7, 1)
UP_TO_DATE_AS_OF = date(2026, 1, 1)

# ── Regexes ───────────────────────────────────────────────────────────────────

# "5-12" in filename
_FILE_RANGE  = re.compile(r"^(\d+)-(\d+)\.txt$")

# "5-12: Chapter I Part A — General" in headers.txt
_HEADER_LINE = re.compile(r"^(\d+)-(\d+)\s*:\s*(.+)$")

# Placeholders typically left by PDF-to-text converters
_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)

# Running headers / footers (page numbers, document title lines)
_FOOTER_LINE = re.compile(
    r"^\s*(?:SOLAS\s+\d{4}|I(?:MO|mo)\s+\w+|\d{1,4}\s*$)",
    re.MULTILINE,
)

# Repeated dashes used as visual separators
_DASH_LINE = re.compile(r"^[\-\u2013\u2014]{4,}\s*$", re.MULTILINE)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_source(raw_dir: Path) -> list[Section]:
    """Parse SOLAS text files into Section objects.

    Args:
        raw_dir: Path to data/raw/solas/ — must contain headers.txt
                 and at least one <start>-<end>.txt file.

    Returns:
        List of Section objects ordered by page range start.

    Raises:
        FileNotFoundError: if headers.txt is absent.
        ValueError:        if headers.txt is empty or no txt files are found.
    """
    headers_path = raw_dir / "headers.txt"
    if not headers_path.exists():
        raise FileNotFoundError(
            f"headers.txt not found at {headers_path}. "
            "Create it with lines like: '5-12: Chapter I Part A — General'"
        )

    section_map = _parse_headers(headers_path)
    if not section_map:
        raise ValueError(f"headers.txt at {headers_path} contains no valid entries.")

    # Collect all range text files, sorted by start page
    txt_files = sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )
    if not txt_files:
        raise ValueError(
            f"No <start>-<end>.txt files found in {raw_dir}. "
            "Expected files named like '5-12.txt'."
        )

    sections: list[Section] = []
    unmatched: list[str] = []

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m  # guaranteed by sorted() filter above
        key = (int(m.group(1)), int(m.group(2)))

        meta = section_map.get(key)
        if meta is None:
            logger.warning("solas: no header entry for %s — skipping", txt_path.name)
            unmatched.append(txt_path.name)
            continue

        raw_text = txt_path.read_text(encoding="utf-8", errors="replace")
        text = _clean_text(raw_text)
        if not text:
            logger.warning("solas: %s is empty after cleaning — skipping", txt_path.name)
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
            "solas: %d file(s) had no header entry: %s",
            len(unmatched), ", ".join(unmatched),
        )

    logger.info(
        "solas: %d txt files → %d sections (%d unmatched)",
        len(txt_files), len(sections), len(unmatched),
    )
    return sections


def dry_run(raw_dir: Path) -> None:
    """Print the page-range → section mapping without reading text files or hitting any API.

    Exits non-zero if headers.txt is missing or malformed.
    """
    headers_path = raw_dir / "headers.txt"
    if not headers_path.exists():
        print(f"ERROR: headers.txt not found at {headers_path}", file=sys.stderr)
        sys.exit(1)

    section_map = _parse_headers(headers_path)
    if not section_map:
        print("ERROR: headers.txt contains no valid entries.", file=sys.stderr)
        sys.exit(1)

    # Collect txt files present on disk
    txt_files = sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )

    matched   = 0
    unmatched = 0

    col_w = 14  # width of "pages" column
    print(f"\n{'Pages':<{col_w}}  {'Matched':<8}  {'section_number':<36}  section_title")
    print("-" * 100)

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m
        key  = (int(m.group(1)), int(m.group(2)))
        meta = section_map.get(key)
        if meta:
            matched += 1
            print(
                f"{txt_path.name:<{col_w}}  {'✓':<8}  "
                f"{meta['section_number']:<36}  {meta['section_title']}"
            )
        else:
            unmatched += 1
            print(f"{txt_path.name:<{col_w}}  {'✗ NO MATCH':<8}")

    # Also flag any header entries with no corresponding txt file
    covered = {
        (int(_FILE_RANGE.match(p.name).group(1)), int(_FILE_RANGE.match(p.name).group(2)))  # type: ignore[union-attr]
        for p in txt_files
    }
    orphan_headers = [k for k in section_map if k not in covered]

    print("-" * 100)
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
    """Parse headers.txt into a dict keyed by (start_page, end_page).

    Each value is a dict with keys:
        section_number        — canonical SOLAS section number
        section_title         — human-readable title
        parent_section_number — parent group for this section
    """
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

        sec_num    = _format_section_number(raw_title)
        sec_title  = _format_section_title(raw_title)
        parent     = _format_parent(raw_title)

        result[(start, end)] = {
            "section_number":        sec_num,
            "section_title":         sec_title,
            "parent_section_number": parent,
        }

    return result


# ── Section number / title formatters ─────────────────────────────────────────
#
# Canonical form: "SOLAS <group>"
#
# Input patterns (case-insensitive):
#   Articles / Preamble                  → "SOLAS Articles"
#   Chapter I Part A - ...               → "SOLAS Ch.I Part A"
#   Chapter II-1 Part B-1 - ...          → "SOLAS Ch.II-1 Part B-1"
#   Annex I / Annex 1                    → "SOLAS Annex I"
#   Appendix                             → "SOLAS Appendix"
#
# The raw title may include a dash-separated description after the structural
# identifier: "Chapter I Part A - General" — we strip that for section_number
# but keep it in section_title.

_RE_CHAPTER_PART = re.compile(
    r"^chapter\s+([IVXivx0-9\-]+)"          # chapter number (Roman or digit)
    r"(?:\s+part\s+([A-Za-z0-9\-]+))?",     # optional Part
    re.IGNORECASE,
)
_RE_ANNEX   = re.compile(r"^annex\s+([IVXivx0-9]+)", re.IGNORECASE)
_RE_ARTICLES = re.compile(r"^(articles|preamble)", re.IGNORECASE)
_RE_APPENDIX = re.compile(r"^appendix", re.IGNORECASE)

# Strip trailing "- description" or "— description" from the structural identifier
_RE_DESC_SUFFIX = re.compile(r"\s*[\-\u2013\u2014].*$")


def _structural_part(raw: str) -> str:
    """Return just the structural identifier of a header title (before any dash + description)."""
    return _RE_DESC_SUFFIX.sub("", raw).strip()


def _format_section_number(raw: str) -> str:
    struct = _structural_part(raw)

    if _RE_ARTICLES.match(struct):
        return "SOLAS Articles"

    if _RE_APPENDIX.match(struct):
        return "SOLAS Appendix"

    m = _RE_ANNEX.match(struct)
    if m:
        roman = m.group(1).upper()
        return f"SOLAS Annex {roman}"

    m = _RE_CHAPTER_PART.match(struct)
    if m:
        ch   = m.group(1).upper()
        part = m.group(2)
        if part:
            return f"SOLAS Ch.{ch} Part {part.upper()}"
        return f"SOLAS Ch.{ch}"

    # Fallback: prefix with SOLAS and normalise whitespace
    return f"SOLAS {struct.strip()}"


def _format_section_title(raw: str) -> str:
    """Return the full human-readable title (structural + description)."""
    # Strip any leading dashes/em-dashes that appear after removing the page range
    return raw.strip().lstrip("\u2013\u2014-").strip()


def _format_parent(raw: str) -> str:
    struct = _structural_part(raw)

    if _RE_ARTICLES.match(struct):
        return "SOLAS"

    if _RE_APPENDIX.match(struct):
        return "SOLAS"

    if _RE_ANNEX.match(struct):
        return "SOLAS Annexes"

    m = _RE_CHAPTER_PART.match(struct)
    if m:
        ch = m.group(1).upper()
        return f"SOLAS Ch.{ch}"

    return "SOLAS"


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Remove PDF artefacts from pre-extracted SOLAS text.

    Operations (in order):
      1. Strip null bytes (PostgreSQL rejects U+0000).
      2. Remove [IMAGE ...] / [FIGURE ...] placeholders.
      3. Remove pure separator lines (-----).
      4. Collapse runs of 3+ blank lines to 2.
      5. Strip leading/trailing whitespace.
    """
    text = text.replace("\x00", "")
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _DASH_LINE.sub("", text)

    # Collapse 3+ consecutive blank lines → 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


# ── CLI entry point (dry-run) ─────────────────────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="SOLAS ingest adapter — dry-run mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify header mapping (no DB or API calls)
  uv run python -m ingest.sources.solas --dry-run data/raw/solas/
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

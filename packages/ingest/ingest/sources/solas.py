"""
SOLAS (International Convention for the Safety of Life at Sea) source adapter.

Input layout — data/raw/solas/
  headers.txt        — alternating title / pp. lines:
                         <title line>
                         pp.: START - END
                       Standalone chapter headers (e.g. "Chapter I" alone) and
                       roman-numeral page ranges (e.g. "pp.: v - x") are skipped.
  <start>-<end>.txt  — pre-extracted text for those pages (e.g. "5-10.txt").

Section number format:
  "SOLAS Articles"
  "SOLAS Protocol 1988 Articles"
  "SOLAS Ch.I Part A"                    (Chapter I, Part A)
  "SOLAS Ch.II-1 Part A-1"              (Chapter II-1, Part A-1)
  "SOLAS Ch.II-1 Unified Interpretations"
  "SOLAS Ch.II-1 Unified Interpretations Appendices"
  "SOLAS Appendix Certificates Form of safety certificate"
  "SOLAS Appendix Unified Interpretation"
  "SOLAS Annex 1"

Parent section number:
  Articles / Protocol Articles   → "SOLAS"
  Ch.X Part Y                    → "SOLAS Ch.X"
  Ch.X (no Part)                 → "SOLAS"
  Ch.X Unified Interpretations   → "SOLAS Ch.X"
  Appendix entries               → "SOLAS"
  Annex N                        → "SOLAS Annexes"

Dry-run mode (no DB/API calls):
  uv run python -m ingest.cli --source solas --dry-run
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

# Filename: "5-10.txt"
_FILE_RANGE = re.compile(r"^(\d+)-(\d+)\.txt$")

# Page-range line in headers.txt: "pp.: 23 - 24" or "pp.: v - x"
_PP_LINE = re.compile(r"^\s*pp\.:?\s+(\S+)\s*-\s*(\S+)")

# Standalone chapter/section header — no colon after the identifier.
# These are skipped as title candidates; they appear immediately before
# the real title line (e.g. "Chapter I" followed by "Chapter I: General...").
_STANDALONE = re.compile(
    r"^(?:Chapter\s+[IVX0-9]+(?:-\d+)?|Appendix|Annexes?)\s*$",
    re.IGNORECASE,
)

# ── Section number / title regexes ────────────────────────────────────────────

# "Chapter II-1: Construction...; Part B-1: Stability"
_RE_CH_PART = re.compile(
    r"(?i)^Chapter\s+([IVX0-9]+(?:-\d+)?).*?;\s*Part\s+([A-Z0-9]+(?:-\d+)?)"
)
# "Chapter V: Safety of navigation"  (no Part)
_RE_CH_ONLY = re.compile(r"(?i)^Chapter\s+([IVX0-9]+(?:-\d+)?)")

# "Appendices to unified interpretations for chapter II-1"  (check BEFORE _RE_UNIFIED_CH)
_RE_UNIFIED_APP_TO_CH = re.compile(
    r"(?i)^Appendices\s+to\s+unified\s+interpretations?\s+for\s+chapter\s+([IVX0-9]+(?:-\d+)?)"
)
# "Unified interpretation(s) for chapter IV"
_RE_UNIFIED_CH = re.compile(
    r"(?i)^(Unified\s+interpretations?)\s+for\s+chapter\s+([IVX0-9]+(?:-\d+)?)"
)
# "Unified interpretation for the appendix"
_RE_UNIFIED_APPENDIX = re.compile(
    r"(?i)^Unified\s+interpretations?\s+for\s+the\s+appendix"
)

# "Appendix: Certificates: Form of safety certificate..."
_RE_APPENDIX_COLON = re.compile(r"(?i)^Appendix\s*:\s*(.+?):\s*(.+)")

# "Annex 1: ..."
_RE_ANNEX_N = re.compile(r"(?i)^Annex\s+(\d+)")

# "Articles of ..."
_RE_ARTICLES = re.compile(r"(?i)^Articles\s+of")
_RE_PROTOCOL_YEAR = re.compile(r"(?i)Protocol\s+of\s+(\d{4})")

# ── Text-cleaning regexes ─────────────────────────────────────────────────────

_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)
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
        ValueError:        if headers.txt yields no valid entries or no txt files.
    """
    headers_path = raw_dir / "headers.txt"
    if not headers_path.exists():
        raise FileNotFoundError(f"headers.txt not found at {headers_path}")

    section_map = _parse_headers(headers_path)
    if not section_map:
        raise ValueError(f"headers.txt at {headers_path} contains no valid entries.")

    txt_files = _sorted_txt_files(raw_dir)
    if not txt_files:
        raise ValueError(f"No <start>-<end>.txt files found in {raw_dir}.")

    sections: list[Section] = []
    unmatched: list[str] = []

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m
        key = (int(m.group(1)), int(m.group(2)))

        meta = section_map.get(key)
        if meta is None:
            logger.warning("solas: no header entry for %s — skipping", txt_path.name)
            unmatched.append(txt_path.name)
            continue

        raw_text = txt_path.read_text(encoding="utf-8", errors="replace")
        text = _clean_text(raw_text)
        if not text:
            logger.warning("solas: %s empty after cleaning — skipping", txt_path.name)
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
    """Print the page-range → section mapping without reading text or calling any API.

    Exits non-zero if headers.txt is missing, empty, or any txt file is unmatched.
    """
    headers_path = raw_dir / "headers.txt"
    if not headers_path.exists():
        print(f"ERROR: headers.txt not found at {headers_path}", file=sys.stderr)
        sys.exit(1)

    section_map = _parse_headers(headers_path)
    if not section_map:
        print("ERROR: headers.txt contains no valid entries.", file=sys.stderr)
        sys.exit(1)

    txt_files = _sorted_txt_files(raw_dir)

    matched   = 0
    unmatched = 0

    col_file = 14
    col_sec  = 42
    print(f"\n{'File':<{col_file}}  {'Status':<6}  {'section_number':<{col_sec}}  section_title")
    print("-" * 110)

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m
        key  = (int(m.group(1)), int(m.group(2)))
        meta = section_map.get(key)
        if meta:
            matched += 1
            print(
                f"{txt_path.name:<{col_file}}  {'ok':<6}  "
                f"{meta['section_number']:<{col_sec}}  {meta['section_title'][:60]}"
            )
        else:
            unmatched += 1
            print(f"{txt_path.name:<{col_file}}  {'MISS':<6}  NO MATCH IN HEADERS")

    # Flag header entries with no txt file
    covered = {
        (int(_FILE_RANGE.match(p.name).group(1)), int(_FILE_RANGE.match(p.name).group(2)))  # type: ignore[union-attr]
        for p in txt_files
    }
    orphans = sorted(k for k in section_map if k not in covered)

    print("-" * 110)
    print(
        f"\nSummary: {len(txt_files)} txt files — "
        f"{matched} matched, {unmatched} unmatched"
        + (f", {len(orphans)} header entries with no txt file" if orphans else "")
    )

    if orphans:
        print("\nHeader entries with no corresponding txt file:")
        for k in orphans:
            meta = section_map[k]
            print(f"  pp.{k[0]}-{k[1]}: {meta['section_number']}")

    if unmatched or orphans:
        sys.exit(1)
    else:
        print("\nAll files matched. [OK]")


# ── Internal helpers ──────────────────────────────────────────────────────────

def _sorted_txt_files(raw_dir: Path) -> list[Path]:
    return sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )


def _parse_headers(headers_path: Path) -> dict[tuple[int, int], dict]:
    """Parse headers.txt into a dict keyed by (start_page, end_page).

    Format (two-line pairs):
        <title line>
        pp.: START - END

    Rules:
      - Lines matching _STANDALONE (e.g. bare "Chapter I", "Appendix", "Annexes")
        are skipped — they appear before the real title and carry no section info.
      - pp.: lines with non-integer page identifiers (roman numerals like v, x)
        are skipped (foreword pages have no corresponding txt file).
      - The title used is the most recent non-standalone, non-pp. line seen before
        the pp.: line.
    """
    result: dict[tuple[int, int], dict] = {}
    pending_title: str | None = None

    for raw_line in headers_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # ── pp.: page-range line ─────────────────────────────────────────────
        pp_m = _PP_LINE.match(line)
        if pp_m:
            start_str, end_str = pp_m.group(1), pp_m.group(2)
            # Skip roman-numeral pages (foreword)
            if not start_str.isdigit() or not end_str.isdigit():
                pending_title = None
                continue
            start, end = int(start_str), int(end_str)
            if pending_title is not None:
                result[(start, end)] = _build_meta(pending_title)
                pending_title = None
            continue

        # ── Standalone chapter/section header — skip ─────────────────────────
        if _STANDALONE.match(line):
            continue

        # ── Title candidate ──────────────────────────────────────────────────
        pending_title = line

    return result


def _build_meta(title: str) -> dict:
    return {
        "section_number":        _format_section_number(title),
        "section_title":         title.strip(),
        "parent_section_number": _format_parent(title),
    }


# ── Section number formatters ─────────────────────────────────────────────────

def _format_section_number(title: str) -> str:
    # "Appendices to unified interpretations for chapter II-1"
    m = _RE_UNIFIED_APP_TO_CH.match(title)
    if m:
        ch = m.group(1).upper()
        return f"SOLAS Ch.{ch} Unified Interpretations Appendices"

    # "Unified interpretation for the appendix"
    if _RE_UNIFIED_APPENDIX.match(title):
        return "SOLAS Appendix Unified Interpretation"

    # "Unified interpretation(s) for chapter X"
    m = _RE_UNIFIED_CH.match(title)
    if m:
        ch    = m.group(2).upper()
        label = _unified_label(m.group(1))
        return f"SOLAS Ch.{ch} {label}"

    # "Articles of the International Convention..."
    if _RE_ARTICLES.match(title):
        yr = _RE_PROTOCOL_YEAR.search(title)
        if yr:
            return f"SOLAS Protocol {yr.group(1)} Articles"
        return "SOLAS Articles"

    # "Chapter II-1: ...; Part B-1: ..."
    m = _RE_CH_PART.match(title)
    if m:
        ch   = m.group(1).upper()
        part = m.group(2).upper()
        return f"SOLAS Ch.{ch} Part {part}"

    # "Appendix: Certificates: Form of safety certificate..."
    m = _RE_APPENDIX_COLON.match(title)
    if m:
        category   = m.group(1).strip()
        descriptor = m.group(2).strip()
        # Use first few words of descriptor to disambiguate entries
        words = descriptor.split()
        # Drop trailing footnote markers like "1"
        while words and re.match(r"^\d+$", words[-1]):
            words.pop()
        short = " ".join(words[:5])
        return f"SOLAS Appendix {category} {short}".rstrip()

    # "Annex 1: ..."
    m = _RE_ANNEX_N.match(title)
    if m:
        return f"SOLAS Annex {m.group(1)}"

    # "Chapter V: Safety of navigation"  (chapter only, no Part)
    m = _RE_CH_ONLY.match(title)
    if m:
        ch = m.group(1).upper()
        return f"SOLAS Ch.{ch}"

    # Fallback — truncate to 120 chars
    return f"SOLAS {title[:120].strip()}"


def _format_parent(title: str) -> str:
    if _RE_UNIFIED_APPENDIX.match(title) or _RE_APPENDIX_COLON.match(title):
        return "SOLAS"

    m = _RE_UNIFIED_APP_TO_CH.match(title)
    if m:
        return f"SOLAS Ch.{m.group(1).upper()}"

    m = _RE_UNIFIED_CH.match(title)
    if m:
        return f"SOLAS Ch.{m.group(2).upper()}"

    if _RE_ARTICLES.match(title):
        return "SOLAS"

    m = _RE_CH_PART.match(title)
    if m:
        return f"SOLAS Ch.{m.group(1).upper()}"

    if _RE_ANNEX_N.match(title):
        return "SOLAS Annexes"

    m = _RE_CH_ONLY.match(title)
    if m:
        return "SOLAS"

    return "SOLAS"


def _unified_label(raw: str) -> str:
    """Return 'Unified Interpretations' or 'Unified Interpretation' preserving plurality."""
    if re.search(r"(?i)interpretations\b", raw):
        return "Unified Interpretations"
    return "Unified Interpretation"


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = _IMAGE_PLACEHOLDER.sub("", text)
    text = _DASH_LINE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── CLI entry point (dry-run via ingest.cli) ──────────────────────────────────

def _main() -> None:
    parser = argparse.ArgumentParser(
        description="SOLAS ingest adapter — standalone dry-run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Use the main CLI instead:
  uv run python -m ingest.cli --source solas --dry-run

Or invoke directly (legacy):
  uv run python -m ingest.sources.solas --dry-run data/raw/solas/
        """,
    )
    parser.add_argument("--dry-run", metavar="RAW_DIR",
                        help="Path to data/raw/solas/")
    args = parser.parse_args()
    if args.dry_run:
        dry_run(Path(args.dry_run))
    else:
        parser.print_help()


if __name__ == "__main__":
    _main()

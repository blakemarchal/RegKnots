"""
MARPOL (International Convention for the Prevention of Pollution from Ships,
1973, as modified by the Protocol of 1978 and subsequent amendments)
source adapter.

Mirrors the SOLAS adapter design: pre-extracted text files per section
page-range plus a headers.txt index. The text is produced upstream by
scripts/ocr_marpol_screenshots.py + scripts/consolidate_marpol_pages.py
since IMO Publishing's e-reader doesn't permit PDF export.

Input layout — data/raw/marpol/
  headers.txt            — one line per page range: "START-END: TITLE"
                           comments start with '#', blank lines ignored.
  <start>-<end>.txt      — consolidated text for those pages, e.g. "41-50.txt"
  extracted/             — internal artifacts (raw OCR cache + pagemap),
                           NOT read by this adapter.

Section number canonical forms:
  "MARPOL Articles"
  "MARPOL Protocol I"
  "MARPOL Protocol II"
  "MARPOL Protocol of 1978"
  "MARPOL Protocol of 1997"
  "MARPOL Annex I Ch.1"               (Chapter 1 of Annex I)
  "MARPOL Annex IV Ch.2"              (etc. through Annex VI)
  "MARPOL Annex I App.II"             (Appendix to an Annex)
  "MARPOL Annex III App."             (Single appendix, no number)
  "MARPOL Annex I UI"                 (Unified Interpretations)
  "MARPOL Annex I UI App.2"           (UI sub-appendices for Annex I)
  "MARPOL Introduction"
  "MARPOL Additional Information 1"   (1, 2, or 3)

Parent section number routing:
  Articles / Protocols / Introduction / Additional Information → "MARPOL"
  Annex I Ch.X / App.X / UI / UI App.X                          → "MARPOL Annex I"
  ... and similarly for Annexes II–VI.

Dry-run mode (no DB/API calls):
  uv run python -m ingest.sources.marpol --dry-run data/raw/marpol/
"""

import argparse
import logging
import re
import sys
from datetime import date
from pathlib import Path

from ingest.models import Section

logger = logging.getLogger(__name__)

SOURCE = "marpol"
TITLE_NUMBER = 0

# MARPOL Consolidated Edition 2022, all amendments in force on 1 November 2022.
SOURCE_DATE      = date(2022, 11, 1)
UP_TO_DATE_AS_OF = date(2022, 11, 1)

# ── Regexes ───────────────────────────────────────────────────────────────────

# Filename "<start>-<end>.txt" — same convention as SOLAS adapter.
_FILE_RANGE  = re.compile(r"^(\d+)-(\d+)\.txt$")

# headers.txt line "<start>-<end>: <title>"
_HEADER_LINE = re.compile(r"^(\d+)-(\d+)\s*:\s*(.+)$")

# Placeholders typically left by PDF-to-text or Vision-OCR conversion
_IMAGE_PLACEHOLDER = re.compile(
    r"\[(?:IMAGE|FIGURE|TABLE|DIAGRAM|PHOTO|CHART|ILLUSTRATION)[^\]]*\]",
    re.IGNORECASE,
)

# Running headers/footers in the IMO Consolidated Edition layout. These
# aren't load-bearing content and just bloat embedding context. Match
# both common variants (e.g., the wrapped section-title chunks at the
# top of every other page).
_HEADER_FOOTER_PATTERNS = [
    re.compile(r"(?im)^.*MARPOL CONSOLIDATED EDITION 2022.*$"),
    re.compile(r"(?im)^.*MARPOL\s+(?:73(?:/78)?|73/78/97).*$"),
    # Standalone numeric page numbers
    re.compile(r"(?m)^\s*\d{1,4}\s*$"),
]

# Repeated dashes used as visual separators
_DASH_LINE = re.compile(r"^[\-–—]{4,}\s*$", re.MULTILINE)

# Page-marker lines emitted by the consolidation step's predecessor
# (the OCR stage). These should already have been stripped by the
# consolidation step, but defensively remove any that survive.
_PAGE_MARKER_LINE = re.compile(
    r"(?im)^===\s*(?:Left page|Right page|Book p\.|Page)?\s*"
    r"(?:\(book p\.|book p\.|p\.)?\s*[\w\d?]+\)?\s*===\s*$"
)


# ── Public API ────────────────────────────────────────────────────────────────

def parse_source(raw_dir: Path) -> list[Section]:
    """Parse MARPOL text files into Section objects.

    Args:
        raw_dir: Path to data/raw/marpol/ — must contain headers.txt
                 and extracted/<start>-<end>.txt files.

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
            "Create it with lines like: '41-50: Annex I Chapter 1 — General'"
        )

    section_map = _parse_headers(headers_path)
    if not section_map:
        raise ValueError(f"headers.txt at {headers_path} contains no valid entries.")

    # Section .txt files live alongside headers.txt at the top of raw_dir,
    # matching the SOLAS adapter convention. The extracted/ subdir holds
    # internal artifacts (raw OCR cache + pagemap) and is not read here.
    txt_files = sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )
    if not txt_files:
        raise ValueError(
            f"No <start>-<end>.txt files found in {raw_dir}. "
            "Expected files named like '41-50.txt'. Run "
            "scripts/consolidate_marpol_pages.py --write-sections first."
        )

    sections: list[Section] = []
    unmatched: list[str] = []

    for txt_path in txt_files:
        m = _FILE_RANGE.match(txt_path.name)
        assert m
        key = (int(m.group(1)), int(m.group(2)))

        meta = section_map.get(key)
        if meta is None:
            logger.warning("marpol: no header entry for %s — skipping", txt_path.name)
            unmatched.append(txt_path.name)
            continue

        raw_text = txt_path.read_text(encoding="utf-8", errors="replace")
        text = _clean_text(raw_text)
        if not text:
            logger.warning("marpol: %s is empty after cleaning — skipping", txt_path.name)
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
            "marpol: %d file(s) had no header entry: %s",
            len(unmatched), ", ".join(unmatched),
        )

    logger.info(
        "marpol: %d txt files → %d sections (%d unmatched)",
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

    txt_files = sorted(
        (p for p in raw_dir.iterdir() if _FILE_RANGE.match(p.name)),
        key=lambda p: int(_FILE_RANGE.match(p.name).group(1)),  # type: ignore[union-attr]
    )

    matched   = 0
    unmatched = 0

    col_w = 14
    print(f"\n{'Pages':<{col_w}}  {'Matched':<8}  {'section_number':<48}  section_title")
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
                f"{meta['section_number']:<48}  {meta['section_title']}"
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

# Matchers operate on the title BEFORE the descriptive suffix. The headers.txt
# title typically reads "Annex I Chapter 1 — General"; we want the structural
# part "Annex I Chapter 1" → "MARPOL Annex I Ch.1".

_RE_DESC_SUFFIX = re.compile(r"\s*[\-–—].*$")

_RE_ARTICLES = re.compile(r"^articles?\s*$", re.IGNORECASE)
_RE_INTRODUCTION = re.compile(r"^introduction\s*$", re.IGNORECASE)
_RE_PROTOCOL = re.compile(
    r"^protocol\s+(?:of\s+)?([IVXivx]+|\d{4})\s*$",
    re.IGNORECASE,
)

# "Annex I" → ("I",); "Annex I Chapter 1" → ("I", "1"); "Annex I Appendix II" → ("I", "App", "II")
# Captures the Annex roman + optional Chapter/Appendix/UI segment.
_RE_ANNEX = re.compile(
    r"^annex\s+([IVXivx]+)"               # Annex roman
    r"(?:\s+(?:"                           # optional <space + (alts)>
        r"(chapter|ch\.?)\s+(\d+|[IVXivx]+)"      # Chapter N
        r"|"
        r"(appendix|app\.?)(?:\s+([IVXivx\d]+))?" # Appendix [number]
        r"|"
        r"(unified\s+interpretations?|UI)"        # UI
    r"))?",
    re.IGNORECASE,
)
_RE_ANNEX_UI_APP = re.compile(
    r"^annex\s+([IVXivx]+)\s+(?:unified\s+interpretations?|UI)\s+"
    r"(?:appendix|app\.?)\s+([IVXivx\d]+)",
    re.IGNORECASE,
)
_RE_ADDL_INFO = re.compile(
    r"^additional\s+information\s+(\d+)",
    re.IGNORECASE,
)


def _structural_part(raw: str) -> str:
    """Return only the structural identifier of a header title."""
    return _RE_DESC_SUFFIX.sub("", raw).strip()


def _format_section_number(raw: str) -> str:
    struct = _structural_part(raw)

    # Articles
    if _RE_ARTICLES.match(struct):
        return "MARPOL Articles"

    # Introduction
    if _RE_INTRODUCTION.match(struct):
        return "MARPOL Introduction"

    # Protocols — handle both Roman ("Protocol I", "Protocol II") and year
    # ("Protocol of 1978", "Protocol of 1997") variants.
    m = _RE_PROTOCOL.match(struct)
    if m:
        marker = m.group(1)
        # Roman or numeric year — keep as-is
        if marker.isdigit():
            return f"MARPOL Protocol of {marker}"
        return f"MARPOL Protocol {marker.upper()}"

    # Additional Information 1/2/3
    m = _RE_ADDL_INFO.match(struct)
    if m:
        return f"MARPOL Additional Information {m.group(1)}"

    # UI Appendix BEFORE generic Annex match (more specific)
    m = _RE_ANNEX_UI_APP.match(struct)
    if m:
        annex = m.group(1).upper()
        sub = m.group(2).upper()
        return f"MARPOL Annex {annex} UI App.{sub}"

    # Annex I / Annex I Ch.X / Annex I App.X / Annex I UI
    m = _RE_ANNEX.match(struct)
    if m:
        annex = m.group(1).upper()
        chapter_kw, chapter_num = m.group(2), m.group(3)
        appendix_kw, appendix_num = m.group(4), m.group(5)
        ui_kw = m.group(6)
        if chapter_kw and chapter_num:
            return f"MARPOL Annex {annex} Ch.{chapter_num.upper()}"
        if appendix_kw:
            if appendix_num:
                return f"MARPOL Annex {annex} App.{appendix_num.upper()}"
            return f"MARPOL Annex {annex} App."
        if ui_kw:
            return f"MARPOL Annex {annex} UI"
        return f"MARPOL Annex {annex}"

    # Fallback — prefix with MARPOL and use whatever the structural part was.
    return f"MARPOL {struct.strip()}"


def _format_section_title(raw: str) -> str:
    """Return the full human-readable title (structural + description)."""
    return raw.strip().lstrip("–—-").strip()


def _format_parent(raw: str) -> str:
    struct = _structural_part(raw)

    # Top-level groupings live under MARPOL itself.
    if (
        _RE_ARTICLES.match(struct)
        or _RE_INTRODUCTION.match(struct)
        or _RE_PROTOCOL.match(struct)
        or _RE_ADDL_INFO.match(struct)
    ):
        return "MARPOL"

    # Annex children (Ch.X / App.X / UI) parent to the Annex itself.
    m_ui_app = _RE_ANNEX_UI_APP.match(struct)
    if m_ui_app:
        return f"MARPOL Annex {m_ui_app.group(1).upper()}"

    m = _RE_ANNEX.match(struct)
    if m:
        annex = m.group(1).upper()
        # Bare "Annex I" alone (rare in headers.txt) → parent = MARPOL.
        # All Ch./App./UI variants → parent = the Annex.
        if any([m.group(2), m.group(4), m.group(6)]):
            return f"MARPOL Annex {annex}"
        return "MARPOL"

    return "MARPOL"


# ── Text cleaning ─────────────────────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Remove PDF/OCR artefacts from pre-extracted MARPOL text.

    Operations (in order):
      1. Strip null bytes (PostgreSQL rejects U+0000).
      2. Remove [IMAGE ...] / [FIGURE ...] placeholders.
      3. Remove residual page-marker lines (=== Left page (book p.X) ===).
      4. Remove running header/footer lines (MARPOL CONSOLIDATED EDITION 2022, etc.).
      5. Remove pure separator lines (-----).
      6. Collapse runs of 3+ blank lines to 2.
      7. Strip leading/trailing whitespace.
    """
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
        description="MARPOL ingest adapter — dry-run mode",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Verify header mapping (no DB or API calls)
  uv run python -m ingest.sources.marpol --dry-run data/raw/marpol/
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

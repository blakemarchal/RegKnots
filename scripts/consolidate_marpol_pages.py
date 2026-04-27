"""Consolidate raw MARPOL OCR transcripts into a per-book-page map.

Sprint D6.11 — the ocr_marpol_screenshots.py output is one file per
screenshot, each containing a two-page book spread under
`=== Left page (book p.N) ===` / `=== Right page (book p.M) ===`
markers. This script:

  1. Walks every transcript in extracted/raw/
  2. Parses out the per-page text via the Left/Right page markers
  3. Builds a dict {book_page_int: text}
  4. Emits two artifacts:
       - extracted/_pagemap.json — full {page: text} dict (debug + reuse)
       - extracted/_pagemap_index.txt — one-line summary per page
         (page_number | first_50_chars) for quickly sketching headers.txt
  5. (Optional, --write-sections): given a headers.txt, writes the
     SOLAS-style data/raw/marpol/extracted/<start>-<end>.txt files that
     the marpol adapter consumes.

Front matter pages with non-numeric labels (Roman 'iii', '?', empty)
are tracked separately under '_roman' / '_unknown' so they can be
inspected but don't pollute the numeric page sequence.

Run on the VPS:

    /root/.local/bin/uv run --directory /opt/RegKnots/packages/ingest \\
        python /opt/RegKnots/scripts/consolidate_marpol_pages.py

    # then, after editing headers.txt:
    uv run ... python ... --write-sections
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

EXTRACTED_DIR = Path("/opt/RegKnots/data/raw/marpol/extracted/raw")
OUT_DIR = Path("/opt/RegKnots/data/raw/marpol/extracted")
HEADERS_PATH = Path("/opt/RegKnots/data/raw/marpol/headers.txt")
# Section files live alongside headers.txt at the top-level marpol dir
# (SOLAS adapter convention). The internal-artefact pagemap stays in
# extracted/ via OUT_DIR above.
SECTION_OUT_DIR = Path("/opt/RegKnots/data/raw/marpol")

# Match either a two-page spread marker:
#   === Left page (book p.<N>) ===
# or a single-page marker (used by the split-fallback or manual paths):
#   === Book p.<N> ===
_PAGE_MARKER_RE = re.compile(
    r"===\s*(?:Left page|Right page|Book p\.|Page)?\s*"
    r"(?:\(book p\.|book p\.|p\.)?\s*"
    r"([\w\d?]+)"
    r"\)?\s*===",
    re.IGNORECASE,
)

# Simpler, more reliable form — strict match for the two formats we
# actually emit. Used for parsing.
_LEFT_RE = re.compile(r"===\s*Left page\s*\(book p\.([^)]+)\)\s*===", re.IGNORECASE)
_RIGHT_RE = re.compile(r"===\s*Right page\s*\(book p\.([^)]+)\)\s*===", re.IGNORECASE)
_BOOK_RE = re.compile(r"===\s*Book p\.([^=\s]+)\s*===", re.IGNORECASE)
_HEADER_LINE_RE = re.compile(r"^(\d+)-(\d+)\s*:\s*(.+)$")


def _parse_transcript(text: str) -> list[tuple[str, str]]:
    """Split a transcript into [(page_label, body), ...].

    Each tuple is one book page. page_label is the exact string captured
    from the marker (could be a number, 'iii', '?', '15-16', etc).
    """
    # Find every marker line + start position
    matches: list[tuple[int, int, str]] = []  # (start, end, label)
    for rx in (_LEFT_RE, _RIGHT_RE, _BOOK_RE):
        for m in rx.finditer(text):
            matches.append((m.start(), m.end(), m.group(1).strip()))
    matches.sort()

    if not matches:
        return []

    pages: list[tuple[str, str]] = []
    for i, (_, end, label) in enumerate(matches):
        next_start = matches[i + 1][0] if i + 1 < len(matches) else len(text)
        body = text[end:next_start].strip()
        pages.append((label, body))
    return pages


def _coerce_page_int(label: str) -> int | None:
    """Return an integer page number if `label` parses cleanly, else None.

    Handles labels like '15', '15-16' (returns 15), '15.' etc. Returns
    None for Roman numerals, '?', and other non-numeric.
    """
    m = re.match(r"^\s*(\d+)", label)
    return int(m.group(1)) if m else None


def build_pagemap() -> tuple[dict[int, str], dict[str, str]]:
    """Walk all OCR transcripts; return (numeric_pages, special_pages).

    numeric_pages: {int_page_num -> body_text}
    special_pages: {label_string -> body_text} for Roman, '?', etc.
    """
    numeric: dict[int, str] = {}
    special: dict[str, str] = {}
    txt_files = sorted(EXTRACTED_DIR.glob("*.txt"))
    for txt_path in txt_files:
        text = txt_path.read_text(encoding="utf-8")
        for label, body in _parse_transcript(text):
            if not body or body == "[blank]":
                continue
            page_int = _coerce_page_int(label)
            if page_int is not None:
                # If the same page shows up twice (e.g., overlapping
                # screenshots), keep the longer transcript — it's
                # almost always the more complete one.
                existing = numeric.get(page_int, "")
                if len(body) > len(existing):
                    numeric[page_int] = body
            else:
                # Roman numeral, '?', etc. — preserved under the raw label.
                if label not in special or len(body) > len(special[label]):
                    special[label] = body
    return numeric, special


def write_index(numeric: dict[int, str], special: dict[str, str]) -> Path:
    """Write _pagemap_index.txt — one line per page with a short preview.

    Useful for sketching headers.txt: skim the index to find chapter /
    annex transitions and note the page numbers.
    """
    out_path = OUT_DIR / "_pagemap_index.txt"
    lines: list[str] = []
    lines.append(f"# MARPOL page map — {len(numeric)} numeric pages, {len(special)} special-label pages")
    lines.append("# Generated by consolidate_marpol_pages.py")
    lines.append("")
    if special:
        lines.append("## Special-label pages (Roman numerals, '?', etc.)")
        for label, body in sorted(special.items()):
            preview = (body[:80] or "").replace("\n", " / ").strip()
            lines.append(f"  [{label}]  {preview}")
        lines.append("")
    lines.append("## Numeric pages")
    for page_num in sorted(numeric):
        body = numeric[page_num]
        preview = (body[:80] or "").replace("\n", " / ").strip()
        lines.append(f"  p.{page_num:>4}  {preview}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def write_pagemap_json(numeric: dict[int, str], special: dict[str, str]) -> Path:
    """Write _pagemap.json — full text per page. For programmatic reuse."""
    out_path = OUT_DIR / "_pagemap.json"
    payload = {
        "numeric": {str(k): v for k, v in sorted(numeric.items())},
        "special": special,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_section_files(numeric: dict[int, str]) -> int:
    """Read headers.txt and write extracted/<start>-<end>.txt section files.

    Each section file concatenates the pages in that range (with a blank
    line between pages). Pages missing from the numeric map are tolerated
    but logged — they'll just contribute empty strings, which is fine for
    the ingest pipeline (chunker handles empty bodies).
    """
    if not HEADERS_PATH.exists():
        print(f"ERROR: {HEADERS_PATH} not found — create it first", file=sys.stderr)
        return 0

    written = 0
    skipped_pages: list[int] = []
    for raw_line in HEADERS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _HEADER_LINE_RE.match(line)
        if not m:
            print(f"WARN: unrecognised line: {raw_line!r}", file=sys.stderr)
            continue
        start, end = int(m.group(1)), int(m.group(2))

        page_texts: list[str] = []
        for p in range(start, end + 1):
            body = numeric.get(p)
            if body:
                page_texts.append(body)
            else:
                skipped_pages.append(p)

        if not page_texts:
            print(f"WARN: section {start}-{end} has no pages with content", file=sys.stderr)
            continue

        out_path = SECTION_OUT_DIR / f"{start}-{end}.txt"
        out_path.write_text("\n\n".join(page_texts) + "\n", encoding="utf-8")
        print(f"WRITE  {start}-{end}.txt  ({len(page_texts)} pages, {sum(len(t) for t in page_texts):,} chars)")
        written += 1

    if skipped_pages:
        # Compress to ranges for legibility
        skipped_pages.sort()
        ranges: list[str] = []
        run_start = run_end = skipped_pages[0]
        for p in skipped_pages[1:]:
            if p == run_end + 1:
                run_end = p
            else:
                ranges.append(f"{run_start}" if run_start == run_end else f"{run_start}-{run_end}")
                run_start = run_end = p
        ranges.append(f"{run_start}" if run_start == run_end else f"{run_start}-{run_end}")
        print(
            f"\nNOTE: {len(skipped_pages)} page(s) referenced in headers.txt had no content: "
            + ", ".join(ranges),
            file=sys.stderr,
        )

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--write-sections",
        action="store_true",
        help="Read headers.txt and write extracted/<start>-<end>.txt files. "
             "Default behavior is to only build _pagemap.json + _pagemap_index.txt.",
    )
    args = parser.parse_args()

    numeric, special = build_pagemap()
    pages_with_content = len(numeric)
    if pages_with_content == 0:
        print("ERROR: no numeric pages found — did you run the OCR step?", file=sys.stderr)
        return 1

    page_min = min(numeric)
    page_max = max(numeric)
    print(f"Numeric pages parsed: {pages_with_content}  (range p.{page_min} – p.{page_max})")
    expected = set(range(page_min, page_max + 1))
    missing = expected - set(numeric)
    if missing:
        sample = sorted(missing)[:20]
        print(f"  WARN: {len(missing)} numeric page(s) missing in range — first 20: {sample}", file=sys.stderr)
    print(f"Special-label pages: {len(special)}")

    json_path = write_pagemap_json(numeric, special)
    idx_path = write_index(numeric, special)
    print(f"Wrote:\n  {json_path}\n  {idx_path}")

    if args.write_sections:
        print()
        n = write_section_files(numeric)
        print(f"\nWrote {n} section file(s) to {SECTION_OUT_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

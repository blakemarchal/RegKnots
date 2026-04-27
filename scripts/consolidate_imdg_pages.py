"""Consolidate raw IMDG OCR transcripts using SCREENSHOT-INDEX keying.

Sprint D6.12 — pivoted from book-page-keying (used for MARPOL) because
the IMDG Code is published as Volume 1 + Volume 2 with overlapping book
page numbers. Page-keyed consolidation silently overwrites Vol 1's
content with Vol 2's (or vice versa) for every colliding page number.

Screenshot-index keying sidesteps the issue: each screenshot is a
unique entry regardless of which volume it captures. headers.txt maps
SCREENSHOT INDEX RANGES (e.g., "5-22: Part 1 General provisions") to
sections.

Walks the screenshots (.png) in lexicographic order (filenames are
timestamped, so this matches chronological / book order), looks up each
file's transcript by SHA from the OCR manifest, and writes:

  - extracted/_index.json          {screenshot_idx: {filename, sha, transcript}}
  - extracted/_index.txt           one line per screenshot — first 80 chars
                                   of transcript, used to draft headers.txt
  - extracted/_chapter_starts.txt  detected chapter/part boundaries with
                                   their screenshot indices, used as a
                                   skeleton for headers.txt

With --write-sections, additionally reads headers.txt and writes the
SOLAS-style data/raw/imdg/<start>-<end>.txt files (where start/end are
screenshot indices, not book pages) for the imdg adapter.

Run on the VPS:

    /root/.local/bin/uv run --directory /opt/RegKnots/packages/ingest \\
        python /opt/RegKnots/scripts/consolidate_imdg_pages.py
    # then, after editing headers.txt:
    /root/.local/bin/uv run ... --write-sections
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCREENSHOT_DIR = Path("/opt/RegKnots/data/raw/imdg")
EXTRACTED_RAW_DIR = SCREENSHOT_DIR / "extracted" / "raw"
OUT_DIR = SCREENSHOT_DIR / "extracted"
MANIFEST_PATH = OUT_DIR / "_manifest.json"
HEADERS_PATH = SCREENSHOT_DIR / "headers.txt"
SECTION_OUT_DIR = SCREENSHOT_DIR

_HEADER_LINE_RE = re.compile(r"^(\d+)-(\d+)\s*:\s*(.+)$")

# Chapter/Part heading patterns — used by the auto-skeleton generator
# to flag screenshots whose transcript starts with a new section.
_CHAPTER_HEAD_RE = re.compile(
    r"(?im)^\s*(?:===\s*[^=]+===\s*)?(?:\n\s*)?"
    r"(PART\s+\d+|Chapter\s+\d+(?:\.\d+)?|APPENDIX\s+[A-Z\d]+|FOREWORD|PREAMBLE|INDEX)\b",
)


def _strip_page_markers(transcript: str) -> str:
    """Remove the `=== Left page ... ===` / `=== Right page ... ===` markers
    so the body text reads as a continuous block. We retain the body only
    because the screenshot-index now carries the ordering information that
    the page markers used to convey.
    """
    return re.sub(
        r"(?im)^===\s*(?:Left page|Right page|Book p\.|Page)?\s*"
        r"(?:\(book p\.|book p\.|p\.)?\s*[\w\d?]+\)?\s*===\s*$",
        "",
        transcript,
    ).strip()


def build_index() -> list[dict]:
    """Walk screenshots in order, pair each with its OCR transcript.

    Returns a list of {idx, filename, sha, transcript_path, body, status,
    error} dicts in screenshot-index order.
    """
    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found — run OCR first", file=sys.stderr)
        sys.exit(1)
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.get("entries", {})

    pngs = sorted(p for p in SCREENSHOT_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".png")
    if not pngs:
        print(f"ERROR: no PNGs in {SCREENSHOT_DIR}", file=sys.stderr)
        sys.exit(1)

    index: list[dict] = []
    for i, png in enumerate(pngs):
        meta = entries.get(png.name, {})
        sha = meta.get("sha", "")
        status = meta.get("status", "missing")
        body = ""
        if status == "ok" and sha:
            txt_path = EXTRACTED_RAW_DIR / f"{sha}.txt"
            if txt_path.exists():
                raw = txt_path.read_text(encoding="utf-8")
                body = _strip_page_markers(raw)
        index.append({
            "idx": i,
            "filename": png.name,
            "sha": sha,
            "status": status,
            "error": meta.get("error"),
            "body": body,
        })
    return index


def write_index_json(index: list[dict]) -> Path:
    """Full body + metadata. Used by the section-writer + downstream tools."""
    out_path = OUT_DIR / "_index.json"
    payload = [
        {
            "idx": e["idx"],
            "filename": e["filename"],
            "sha": e["sha"],
            "status": e["status"],
            "error": e["error"],
            "body": e["body"],
        }
        for e in index
    ]
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return out_path


def write_index_summary(index: list[dict]) -> Path:
    """One-line preview per screenshot — used to draft headers.txt by hand."""
    out_path = OUT_DIR / "_index.txt"
    lines: list[str] = []
    lines.append(f"# IMDG screenshot index — {len(index)} entries")
    lines.append("# Generated by consolidate_imdg_pages.py")
    lines.append("# Format: idx [status]  first 100 chars of transcript")
    lines.append("")
    for e in index:
        if e["status"] == "ok":
            preview = e["body"][:100].replace("\n", " / ").strip()
            lines.append(f"  {e['idx']:>4}  [ok]   {preview}")
        else:
            err = (e["error"] or "no transcript")[:80]
            lines.append(f"  {e['idx']:>4}  [{e['status']:<5}]  {err}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def write_chapter_starts(index: list[dict]) -> Path:
    """Auto-detect chapter / part / appendix boundaries.

    A heuristic: scan each transcript's first ~200 chars for a heading
    like "PART 1", "Chapter 2.3", "APPENDIX A", "FOREWORD", "INDEX". When
    one is found AND it's structurally first (i.e., near the top of the
    transcript), record it as a probable section start.

    Output is a draft skeleton for headers.txt — the human still needs
    to assign the END index of each section (typically = next start - 1).
    """
    out_path = OUT_DIR / "_chapter_starts.txt"
    lines: list[str] = ["# Auto-detected chapter / part / appendix boundaries.",
                        "# Use to skeleton out headers.txt by setting end = next_start - 1.",
                        "# Format: idx  detected_heading  transcript_preview",
                        ""]
    for e in index:
        if e["status"] != "ok":
            continue
        head = e["body"][:300]
        m = _CHAPTER_HEAD_RE.search(head)
        if not m:
            continue
        detected = m.group(1).strip()
        preview = head[:140].replace("\n", " / ").strip()
        lines.append(f"  {e['idx']:>4}  {detected:<24}  {preview}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def write_section_files(index: list[dict]) -> int:
    """Read headers.txt; concatenate transcripts in each idx range into
    SECTION_OUT_DIR/<start>-<end>.txt for the imdg adapter to consume.
    """
    if not HEADERS_PATH.exists():
        print(f"ERROR: {HEADERS_PATH} not found — create it first", file=sys.stderr)
        return 0

    body_by_idx: dict[int, str] = {
        e["idx"]: e["body"] for e in index if e["status"] == "ok" and e["body"]
    }

    written = 0
    skipped: list[int] = []
    for raw_line in HEADERS_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        m = _HEADER_LINE_RE.match(line)
        if not m:
            print(f"WARN: unrecognised line: {raw_line!r}", file=sys.stderr)
            continue
        start, end = int(m.group(1)), int(m.group(2))
        bodies = []
        for i in range(start, end + 1):
            body = body_by_idx.get(i)
            if body:
                bodies.append(body)
            else:
                skipped.append(i)
        if not bodies:
            print(f"WARN: section {start}-{end} has no content", file=sys.stderr)
            continue
        out_path = SECTION_OUT_DIR / f"{start}-{end}.txt"
        out_path.write_text("\n\n".join(bodies) + "\n", encoding="utf-8")
        print(f"WRITE  {start}-{end}.txt  ({len(bodies)} screenshots, "
              f"{sum(len(b) for b in bodies):,} chars)")
        written += 1

    if skipped:
        skipped.sort()
        ranges: list[str] = []
        run_start = run_end = skipped[0]
        for i in skipped[1:]:
            if i == run_end + 1:
                run_end = i
            else:
                ranges.append(f"{run_start}" if run_start == run_end else f"{run_start}-{run_end}")
                run_start = run_end = i
        ranges.append(f"{run_start}" if run_start == run_end else f"{run_start}-{run_end}")
        print(
            f"\nNOTE: {len(skipped)} screenshot index/indices in headers.txt "
            f"had no transcript: {', '.join(ranges)}",
            file=sys.stderr,
        )

    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--write-sections",
        action="store_true",
        help="Read headers.txt and write <start>-<end>.txt section files. "
             "Default: only build _index.json + _index.txt + _chapter_starts.txt",
    )
    args = parser.parse_args()

    index = build_index()
    ok = sum(1 for e in index if e["status"] == "ok")
    err = len(index) - ok
    print(f"Indexed {len(index)} screenshots: {ok} OK, {err} not OK")

    json_path = write_index_json(index)
    txt_path = write_index_summary(index)
    starts_path = write_chapter_starts(index)
    print(f"Wrote:\n  {json_path}\n  {txt_path}\n  {starts_path}")

    if args.write_sections:
        print()
        n = write_section_files(index)
        print(f"\nWrote {n} section file(s) to {SECTION_OUT_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

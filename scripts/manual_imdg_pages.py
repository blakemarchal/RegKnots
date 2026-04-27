"""Inject Blake's manual transcriptions for the 7 IMDG OCR holdouts.

Sprint D6.12b — IMDG dataset had 7 screenshots that Anthropic's output
content filter persistently blocked even after split-fallback. Blake
manually transcribed them from the IMO viewer into one text file with
'---' separators between sections, in chronological screenshot order.

This script:
  1. Reads `data/raw/imdg/_failed_for_review/imdg - missing.txt`
  2. Splits on lines containing only `---`
  3. Pairs each section with the next failed screenshot (in
     chronological order, matching the order of the manifest entries
     marked status=error)
  4. Writes each transcript to `extracted/raw/<sha>.txt` using the
     same envelope Sonnet OCR produces — so the screenshot-index
     consolidator can't tell them apart from auto-OCR'd content
  5. Updates the manifest entry to status=ok with source=manual_transcription

Idempotent — re-running just overwrites the same files.

Run on the VPS (where the screenshots + manifest live):

    /root/.local/bin/uv run --directory /opt/RegKnots/packages/ingest \\
        python /opt/RegKnots/scripts/manual_imdg_pages.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

IMDG_DIR = Path("/opt/RegKnots/data/raw/imdg")
SCREENSHOT_DIR = IMDG_DIR
EXTRACTED_DIR = IMDG_DIR / "extracted" / "raw"
MANIFEST_PATH = IMDG_DIR / "extracted" / "_manifest.json"
MISSING_FILE = IMDG_DIR / "_failed_for_review" / "imdg - missing.txt"


def _file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _parse_sections(text: str) -> list[str]:
    """Split on lines whose content (after strip) is exactly '---'."""
    sections: list[str] = []
    buf: list[str] = []
    for line in text.splitlines():
        if line.strip() == "---":
            section = "\n".join(buf).strip()
            if section:
                sections.append(section)
            buf = []
        else:
            buf.append(line)
    final = "\n".join(buf).strip()
    if final:
        sections.append(final)
    return sections


def main() -> int:
    if not MISSING_FILE.exists():
        # Allow running from local dev too — try the local path
        local_alt = Path(
            "/c/Users/Blake Marchal/Documents/RegKnots/data/raw/imdg/_failed_for_review/imdg - missing.txt"
        )
        if local_alt.exists():
            print(f"NOTE: using local path {local_alt}")
        else:
            print(f"ERROR: {MISSING_FILE} not found", file=sys.stderr)
            return 1

    text = MISSING_FILE.read_text(encoding="utf-8")
    sections = _parse_sections(text)
    print(f"Parsed {len(sections)} sections from {MISSING_FILE.name}")

    if not MANIFEST_PATH.exists():
        print(f"ERROR: {MANIFEST_PATH} not found", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    entries = manifest.setdefault("entries", {})

    # Find failed screenshots in chronological / screenshot-index order
    all_pngs = sorted(
        p.name for p in SCREENSHOT_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".png"
    )
    failed_in_order = [
        name for name in all_pngs
        if entries.get(name, {}).get("status") == "error"
    ]
    print(f"Found {len(failed_in_order)} failed screenshots in manifest")

    if len(sections) != len(failed_in_order):
        print(
            f"WARN: {len(sections)} sections vs {len(failed_in_order)} failed screenshots — "
            "pairing in order, extras will be skipped",
            file=sys.stderr,
        )

    pairs = list(zip(failed_in_order, sections))
    written = 0
    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)

    for png_name, body in pairs:
        png_path = SCREENSHOT_DIR / png_name
        if not png_path.exists():
            print(f"WARN: missing PNG {png_name!r} — skipping", file=sys.stderr)
            continue
        sha = _file_sha(png_path)
        out_path = EXTRACTED_DIR / f"{sha}.txt"
        # Wrap the body in the same Book p.? envelope Sonnet emits when
        # the page number can't be determined. Consolidator strips this
        # marker on read; the index ordering uses screenshot index, not
        # page number.
        wrapped = f"=== Book p.? ===\n\n{body.strip()}\n"
        out_path.write_text(wrapped, encoding="utf-8")

        idx = all_pngs.index(png_name)
        entries[png_name] = {
            "sha": sha,
            "status": "ok",
            "char_count": len(wrapped),
            "source": "manual_transcription",
        }
        print(
            f"OK  idx={idx:>3}  {png_name[-30:]} -> {sha[:12]}…  "
            f"({len(body):,} chars)"
        )
        written += 1

    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)
    print(f"\nWrote {written} manual transcript file(s); manifest updated.")

    # Quick sanity: any error entries left?
    remaining_errors = sum(1 for v in entries.values() if v.get("status") == "error")
    if remaining_errors:
        print(f"\nWARN: {remaining_errors} error entries remain in the manifest", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

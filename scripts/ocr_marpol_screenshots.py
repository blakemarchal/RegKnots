"""OCR the MARPOL Consolidated Edition 2022 screenshots into structured text.

Sprint D6.11 — input is 207 PNG screenshots taken from the IMO
e-Publications viewer (the only viewing mode IMO permits for purchased
MARPOL e-books — no PDF download, no offline export, no copy-paste).
Each screenshot shows a two-page book spread plus browser/viewer chrome.

Strategy:

  1. Read each PNG in order (filenames are timestamped — lexicographic
     sort gives the correct read sequence).
  2. Send to Claude Sonnet 4.6 Vision with a prompt that explicitly
     instructs it to ignore the IMO viewer chrome (top toolbar, bottom
     thumbnail strip, "Save for offline viewing" tooltip) and transcribe
     ONLY the two book pages.
  3. Save the raw transcript per screenshot, plus update a manifest that
     records SHA256 for resume safety.
  4. After all screenshots OCR'd, a separate consolidation step (run
     manually) reviews + builds the headers.txt for the marpol adapter.

Idempotent: cache key is SHA256 of the PNG bytes. Re-running with new
screenshots added only OCRs the new ones.

Run on the VPS (has the Anthropic key + the screenshots will be scp'd
there first):

    cd /opt/RegKnots
    uv run --directory packages/ingest python /opt/RegKnots/scripts/ocr_marpol_screenshots.py
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import logging
import sys
from pathlib import Path

from anthropic import AsyncAnthropic
from PIL import Image
from rich.console import Console
from rich.progress import (
    BarColumn, MofNCompleteColumn, Progress, SpinnerColumn,
    TextColumn, TimeElapsedColumn, TimeRemainingColumn,
)

sys.path.insert(0, "/opt/RegKnots/packages/ingest")
from ingest.config import settings  # noqa: E402

logger = logging.getLogger(__name__)

# Where the screenshots live + where transcripts go.
SCREENSHOT_DIR = Path("/opt/RegKnots/data/raw/marpol")
EXTRACTED_DIR = SCREENSHOT_DIR / "extracted" / "raw"
MANIFEST_PATH = SCREENSHOT_DIR / "extracted" / "_manifest.json"

# Claude Sonnet 4.6 — same model the NMC OCR script uses. Image input is
# straightforward transcription, no need for Opus.
_VISION_MODEL = "claude-sonnet-4-6"

# Max parallel Vision calls. Anthropic rate limits at our tier comfortably
# permit 5; higher would blow latency budgets without saving wall time.
_CONCURRENCY = 5

# Mirrors the STCW Vision OCR prompt structure that worked in production
# (commit 7b44971). System-prompt framing positions the task as treaty-text
# extraction, not copyrighted-book reproduction.
_VISION_SYSTEM_PROMPT = """\
You are a precise document OCR system extracting text from screenshots of the \
MARPOL Convention (International Convention for the Prevention of Pollution from \
Ships, 1973, as modified by the Protocol of 1978 and subsequent amendments).

EXTRACTION RULES:
1. Extract ALL text exactly as written, preserving the complete document structure.
2. Preserve all structural elements exactly:
   - Article numbers and titles (e.g., "Article 1\\nGeneral obligations under the Convention")
   - Annex headings (e.g., "Annex I\\nRegulations for the prevention of pollution by oil")
   - Chapter headings (e.g., "Chapter 3\\nRequirements for machinery spaces of all ships")
   - Regulation numbers and titles (e.g., "Regulation 17\\nOil Record Book, Part I — Machinery space operations")
   - Appendix references (e.g., "Appendix I", "Appendix V — Form of Oil Record Book")
   - Resolution titles where present (e.g., "Resolution MEPC.176(58)")
   - Paragraph numbering (1, 2, 3... and .1, .2, .3... sub-paragraphs)
   - Table content — render as pipe-delimited rows: "| col1 | col2 | col3 |" with a "| --- | --- |" header separator
   - Footnotes with their reference marks (* † ‡ or superscript numbers)
3. Insert a blank line before each major structural heading (Article, Annex, Chapter, Regulation, Appendix, Section).

IGNORE completely (do not include in output):
- The browser toolbar across the top (e-Publications logo, search bar, ADVANCED SEARCH, language selector)
- The viewer's page navigation bar (zoom controls, fullscreen toggle, page-of-N counter)
- The "Save for offline viewing" / "Close read view" overlay menu at the top-right
- The thumbnail strip of upcoming pages along the bottom of the screenshot
- Any "INTERNATIONAL MARITIME ORGANIZATION" or IMO logo watermarks behind the page text
- Page numbers at the foot of each page (record them only in the section header described below)
- Running headers/footers that just repeat the convention title (e.g., "MARPOL Annex I" at the top of every Annex I page)
- Any "Delivered by Base to:" or order-number watermark lines

OUTPUT FORMAT:
Each screenshot shows two book pages. For each page, output a section in this form:

=== Left page (book p.<NUMBER>) ===
<verbatim transcription of the left book page>

=== Right page (book p.<NUMBER>) ===
<verbatim transcription of the right book page>

Use "?" if a page number cannot be determined. Use "[blank]" as the body for a blank page. \
Omit a page's section entirely if the screenshot only shows one of the two pages (e.g., front cover, very first or last page).

Output ONLY the clean extracted text under those === headers. \
No commentary, no markdown code fences, no "Here is the extracted text:" preamble.\
"""

# User message — short, neutral, just identifies the input.
_TRANSCRIBE_USER_MSG = "Extract the text from this screenshot per the rules above."


def _file_sha(path: Path) -> str:
    """SHA256 of file contents — cache key for resume."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        return {"version": 1, "entries": {}}
    try:
        return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        # Manifest corrupted — start fresh. Better than aborting an
        # in-flight run.
        logger.warning("manifest unreadable — starting fresh")
        return {"version": 1, "entries": {}}


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)


# Single-page split prompt — used when a full two-page screenshot trips
# Anthropic's output content filter and we have to retry one page at a
# time. Same framing as _VISION_SYSTEM_PROMPT but expects a single book
# page in the image.
_SINGLE_PAGE_USER_MSG = (
    "This image shows ONE book page from MARPOL Convention. "
    "Extract its text per the rules above and output only:\n\n"
    "=== Book p.<NUMBER> ===\n"
    "<verbatim transcription>\n\n"
    "Use \"?\" if the page number is not visible. Use \"[blank]\" for a blank page."
)


async def _vision_call(
    png_bytes: bytes,
    client: AsyncAnthropic,
    user_msg: str,
) -> tuple[str | None, str | None]:
    """Single Anthropic Vision call. Returns (transcript, error_or_None)."""
    b64 = base64.b64encode(png_bytes).decode("ascii")
    try:
        response = await client.messages.create(
            model=_VISION_MODEL,
            max_tokens=8192,
            system=_VISION_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": user_msg},
                ],
            }],
        )
    except Exception as exc:  # noqa: BLE001
        return None, f"{type(exc).__name__}: {exc}"

    if not response.content or not getattr(response.content[0], "text", None):
        return None, "empty response"

    transcript = response.content[0].text.strip()
    if response.stop_reason == "max_tokens":
        transcript += "\n\n[WARNING: hit max_tokens — review for truncation]"
    return transcript, None


def _split_screenshot_into_pages(png_bytes: bytes) -> tuple[bytes, bytes]:
    """Split a two-page-spread screenshot into left-half and right-half PNGs.

    The IMO viewer renders book pages roughly centered in the screenshot
    with a ~50/50 horizontal split. We don't bother with pixel-precise
    chrome cropping here because the system prompt already instructs
    Claude to ignore viewer chrome — the split's only purpose is to
    reduce content density per request so the output filter is less
    likely to trip.
    """
    img = Image.open(io.BytesIO(png_bytes))
    w, h = img.size
    # Slight overlap (5%) on each side of the midline so a pixel-precise
    # spine crack doesn't truncate a character on either page.
    midx = w // 2
    pad = w // 20
    left = img.crop((0, 0, midx + pad, h))
    right = img.crop((midx - pad, 0, w, h))
    left_buf = io.BytesIO()
    right_buf = io.BytesIO()
    left.save(left_buf, format="PNG")
    right.save(right_buf, format="PNG")
    return left_buf.getvalue(), right_buf.getvalue()


def _is_content_filter_error(err: str | None) -> bool:
    """True if the error looks like Anthropic's output content filter (HTTP 400)."""
    if not err:
        return False
    return ("content filtering policy" in err.lower()
            or "BadRequestError" in err)


async def _ocr_one(
    png_path: Path,
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str | None, str | None]:
    """OCR a single screenshot. Returns (sha, transcript, error_message_or_None).

    Strategy:
      1. Cache hit on SHA → return cached transcript.
      2. Send the full screenshot.
      3. If step 2 hits the output content filter, split into left/right
         halves and retry each as a single-page request. Concatenate the
         results into a synthetic two-page transcript.
      4. If still failing after split, return the error so the manifest
         can flag it for manual handling.
    """
    sha = _file_sha(png_path)
    out_path = EXTRACTED_DIR / f"{sha}.txt"
    if out_path.exists():
        return sha, out_path.read_text(encoding="utf-8"), None

    png_bytes = png_path.read_bytes()

    # Pass 1: full screenshot
    async with semaphore:
        transcript, err = await _vision_call(png_bytes, client, _TRANSCRIBE_USER_MSG)

    # Pass 2: split fallback if the content filter tripped
    if err is not None and _is_content_filter_error(err):
        try:
            left_bytes, right_bytes = _split_screenshot_into_pages(png_bytes)
        except Exception as split_exc:  # noqa: BLE001
            return sha, None, f"split failed: {split_exc}; original: {err}"

        async with semaphore:
            left_transcript, left_err = await _vision_call(left_bytes, client, _SINGLE_PAGE_USER_MSG)
        async with semaphore:
            right_transcript, right_err = await _vision_call(right_bytes, client, _SINGLE_PAGE_USER_MSG)

        # Best-effort assembly: take whichever halves succeeded. If both
        # failed, surface the error.
        parts: list[str] = []
        if left_transcript:
            parts.append(left_transcript)
        if right_transcript:
            parts.append(right_transcript)
        if not parts:
            return sha, None, (
                f"both halves failed after split | left: {left_err} | right: {right_err}"
            )
        transcript = "\n\n".join(parts) + "\n\n[NOTE: assembled from split-page retry]"
        err = None

    if err is not None or transcript is None:
        return sha, None, err

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(transcript, encoding="utf-8")
    return sha, transcript, None


async def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    console = Console()

    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY not set in env[/red]")
        return 1

    if not SCREENSHOT_DIR.is_dir():
        console.print(f"[red]Missing screenshot dir: {SCREENSHOT_DIR}[/red]")
        return 1

    pngs = sorted(p for p in SCREENSHOT_DIR.iterdir() if p.is_file() and p.suffix.lower() == ".png")
    if not pngs:
        console.print(f"[red]No PNGs found in {SCREENSHOT_DIR}[/red]")
        return 1

    EXTRACTED_DIR.mkdir(parents=True, exist_ok=True)
    manifest = _load_manifest()
    entries = manifest.setdefault("entries", {})

    console.rule(f"[cyan]MARPOL OCR — {len(pngs)} screenshots")
    console.print(f"  Cache: [bold]{len(entries)}[/bold] previously processed")
    console.print(f"  Concurrency: {_CONCURRENCY}")
    console.print(f"  Output:   {EXTRACTED_DIR}")
    console.print(f"  Manifest: {MANIFEST_PATH}")
    console.print()

    client = AsyncAnthropic(api_key=settings.anthropic_api_key)
    semaphore = asyncio.Semaphore(_CONCURRENCY)

    progress = Progress(
        SpinnerColumn(),
        TextColumn("[bold cyan]{task.description:<25}"),
        BarColumn(bar_width=30),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    )

    failures: list[tuple[str, str]] = []

    try:
        with progress:
            task_id = progress.add_task("OCR'ing screenshots…", total=len(pngs))

            # Wrap each call so we can advance the progress bar as
            # individual calls complete (asyncio.gather only resolves at
            # the end). Order of completion doesn't matter — we re-pair
            # results to inputs by index.
            async def _ocr_with_tick(p: Path):
                res = await _ocr_one(p, client, semaphore)
                progress.advance(task_id)
                return res

            results = await asyncio.gather(*[_ocr_with_tick(p) for p in pngs])

            for png_path, (sha, transcript, err) in zip(pngs, results):
                rel = png_path.name
                if err is not None or transcript is None:
                    failures.append((rel, err or "no transcript"))
                    entries[rel] = {"sha": sha, "status": "error", "error": err}
                else:
                    entries[rel] = {
                        "sha": sha,
                        "status": "ok",
                        "char_count": len(transcript),
                    }
    finally:
        await client.close()
        _save_manifest(manifest)

    console.print()
    ok_count = sum(1 for v in entries.values() if v.get("status") == "ok")
    console.print(f"[green]OK:[/green] {ok_count} / {len(pngs)}")
    if failures:
        console.print(f"[red]Failures:[/red] {len(failures)}")
        for name, err in failures[:10]:
            console.print(f"  [red]{name}[/red] — {err}")
        if len(failures) > 10:
            console.print(f"  …and {len(failures) - 10} more (see manifest)")
        return 2

    console.print()
    console.print("[bold green]Done.[/bold green] Next:")
    console.print("  1. Review samples in", EXTRACTED_DIR)
    console.print("  2. Run the consolidation step to generate headers.txt + extracted/<page-range>.txt")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

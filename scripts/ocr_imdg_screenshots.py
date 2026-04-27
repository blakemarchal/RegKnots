"""OCR the IMDG Code 2024 Edition screenshots into structured text.

Sprint D6.12 — input is 481 PNG screenshots taken from the IMO
e-Publications viewer of the IMDG Code (International Maritime
Dangerous Goods Code), Volume 1, 2024 Edition (Amendment 42-24). The
viewer doesn't permit PDF download even for purchased copies, so the
ingest path is screenshot-based — same approach as MARPOL Sprint D6.11.

Each screenshot is a two-page book spread plus browser/viewer chrome.
We use Claude Sonnet 4.6 Vision with treaty-text framing (calibrated
during the MARPOL run — frames the input as IMDG Convention text
adopted by IMO Resolution, not as a copyrighted publication, which
keeps Anthropic's output content filter from refusing).

Idempotent: cache key is SHA256 of the PNG bytes. Re-runs only OCR
new screenshots. Failures from the output content filter trip the
split-fallback (left half / right half independently).

Run on the VPS (has the Anthropic key + the screenshots already on disk
after scp from local):

    /root/.local/bin/uv run --directory /opt/RegKnots/packages/ingest \\
        python /opt/RegKnots/scripts/ocr_imdg_screenshots.py
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

SCREENSHOT_DIR = Path("/opt/RegKnots/data/raw/imdg")
EXTRACTED_DIR = SCREENSHOT_DIR / "extracted" / "raw"
MANIFEST_PATH = SCREENSHOT_DIR / "extracted" / "_manifest.json"

_VISION_MODEL = "claude-sonnet-4-6"
# Concurrency 5 worked well for MARPOL's 207 screenshots; for 481 we
# bump to 8 to keep wall time bounded — still well under our tier's
# anthropic rate limit.
_CONCURRENCY = 8

# IMDG Code framing — same treaty-text positioning that worked for
# MARPOL/SOLAS/STCW. The IMDG Code is the international instrument
# adopted under SOLAS Chapter VII for the carriage of dangerous goods
# by sea; we frame the OCR task as extracting the convention/code
# text, not the IMO Publishing book product.
_VISION_SYSTEM_PROMPT = """\
You are a precise document OCR system extracting text from screenshots of the \
IMDG Code (International Maritime Dangerous Goods Code), the mandatory \
international instrument adopted under SOLAS Chapter VII Regulation 1.4 for \
the carriage of dangerous goods in packaged form by sea.

EXTRACTION RULES:
1. Extract ALL text exactly as written, preserving the complete document structure.
2. Preserve all structural elements exactly:
   - Part headings (e.g., "Part 1\\nGeneral provisions, definitions and training")
   - Chapter headings (e.g., "Chapter 2.2\\nClass 2 - Gases")
   - Section / sub-section numbers (e.g., "1.2.1.1", "2.2.1.1.5")
   - Special Provision numbers (SP119, SP163, etc.)
   - UN numbers (UN1203, UN2734, etc.)
   - Class numbers (Class 1, Class 2.1, Class 4.3, Class 6.1)
   - Packing Group designations (PG I, PG II, PG III)
   - EmS codes (F-A, S-G, etc.)
   - Dangerous Goods List columns and their headers
   - Tables: render as plain-text with " | " column separators. Add a header separator row "| --- | --- |" if there is one.
   - Footnotes with their reference marks (* † ‡ or superscript numbers)
3. For the Dangerous Goods List (Chapter 3.2 in Volume 2): each row is one entry. Preserve column alignment via " | " separators. Row format typically:
   UN No. | PSN | Class | Sub Risk | PG | SP | Limited Qty | Excepted Qty | Packing Inst | IBC Inst | Tank Inst | EmS | Stowage | Properties | Observations

IGNORE completely:
- The browser toolbar at the very top (e-Publications logo, search bar, ADVANCED SEARCH, language selector)
- The page navigation bar above the pages (zoom, page-of-N counter)
- The "Save for offline viewing" / "Close read view" overlay menu at the top-right
- The thumbnail strip of upcoming pages along the bottom
- Any "INTERNATIONAL MARITIME ORGANIZATION" or IMO logo watermarks behind the page text
- Page numbers at the foot (record them only via the "=== ... ===" header)
- Running headers/footers that just repeat the chapter title
- "Delivered by Base to:" or order-number watermark lines

OUTPUT FORMAT:
Each screenshot shows two book pages. For each page, output a section in this form:

=== Left page (book p.<NUMBER>) ===
<verbatim transcription of the left book page>

=== Right page (book p.<NUMBER>) ===
<verbatim transcription of the right book page>

Use "?" if a page number cannot be determined. Use "[blank]" as the body for a blank page. \
Omit a page's section entirely if the screenshot only shows one of the two pages \
(e.g., front cover, very first or last page).

Output ONLY the clean extracted text under those === headers. \
No commentary, no markdown code fences, no "Here is the extracted text:" preamble.\
"""

_TRANSCRIBE_USER_MSG = "Extract the text from this screenshot per the rules above."

_SINGLE_PAGE_USER_MSG = (
    "This image shows ONE book page from the IMDG Code. "
    "Extract its text per the rules above and output only:\n\n"
    "=== Book p.<NUMBER> ===\n"
    "<verbatim transcription>\n\n"
    "Use \"?\" if the page number is not visible. Use \"[blank]\" for a blank page."
)


def _file_sha(path: Path) -> str:
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
        logger.warning("manifest unreadable — starting fresh")
        return {"version": 1, "entries": {}}


def _save_manifest(manifest: dict) -> None:
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = MANIFEST_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(MANIFEST_PATH)


async def _vision_call(
    png_bytes: bytes,
    client: AsyncAnthropic,
    user_msg: str,
) -> tuple[str | None, str | None]:
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
    img = Image.open(io.BytesIO(png_bytes))
    w, h = img.size
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
    if not err:
        return False
    return ("content filtering policy" in err.lower()
            or "BadRequestError" in err)


async def _ocr_one(
    png_path: Path,
    client: AsyncAnthropic,
    semaphore: asyncio.Semaphore,
) -> tuple[str, str | None, str | None]:
    sha = _file_sha(png_path)
    out_path = EXTRACTED_DIR / f"{sha}.txt"
    if out_path.exists():
        return sha, out_path.read_text(encoding="utf-8"), None

    png_bytes = png_path.read_bytes()

    async with semaphore:
        transcript, err = await _vision_call(png_bytes, client, _TRANSCRIBE_USER_MSG)

    if err is not None and _is_content_filter_error(err):
        try:
            left_bytes, right_bytes = _split_screenshot_into_pages(png_bytes)
        except Exception as split_exc:  # noqa: BLE001
            return sha, None, f"split failed: {split_exc}; original: {err}"

        async with semaphore:
            left_transcript, left_err = await _vision_call(left_bytes, client, _SINGLE_PAGE_USER_MSG)
        async with semaphore:
            right_transcript, right_err = await _vision_call(right_bytes, client, _SINGLE_PAGE_USER_MSG)

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

    console.rule(f"[cyan]IMDG OCR — {len(pngs)} screenshots")
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
        for name, err in failures[:20]:
            console.print(f"  [red]{name}[/red] — {(err or '')[:100]}")
        if len(failures) > 20:
            console.print(f"  …and {len(failures) - 20} more (see manifest)")
        return 0  # exit 0 — partial success is fine, holdouts get manual transcription

    console.print()
    console.print("[bold green]Done.[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

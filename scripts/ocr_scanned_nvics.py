"""OCR pass for scanned NVIC PDFs.

The 2026-05-09 corpus survey identified ~55 NVIC PDFs that are on
disk under data/raw/nvic/ but not in the regulations table. The cause
is that pdfplumber returns 0 chars from these — they're scanned image
documents, not text-extractable.

This script:
  1. Identifies which NVICs are in the local index but not in the DB.
  2. For each, checks whether pdfplumber can extract text (skip if yes —
     they may have failed for a different reason).
  3. Sends the PDF to Anthropic's vision API (Claude is good at maritime
     regulatory text extraction; preserves section structure).
  4. Saves the extracted text to data/ocr/nvic/{number}.txt.
  5. Optionally injects the extracted text back through the existing
     parser via manual_add to land in the DB.

Cost: each NVIC averages 8-15 pages; vision API is roughly $0.01-0.03
per page (input) + tiny output. Total budget for the full 55-PDF batch
is ~$5-15 — well inside what's reasonable.

Run:
  cd /opt/RegKnots/packages/ingest  # for dependencies
  /root/.local/bin/uv run --project /opt/RegKnots/packages/ingest \\
      python /opt/RegKnots/scripts/ocr_scanned_nvics.py [--dry-run] [--limit N]

Flags:
  --dry-run   List the targets, don't call the API
  --limit N   Stop after N successful OCRs (for cost-bounded test runs)
  --force     Re-OCR even if a sidecar text file already exists

Outputs:
  data/ocr/nvic/{number}.txt          extracted text per NVIC
  data/ocr/nvic/_summary.json         per-run audit log

Idempotent: if a sidecar .txt already exists, it's skipped (unless --force).
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import logging
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pdfplumber

REPO = Path("/opt/RegKnots")
RAW_NVIC = REPO / "data" / "raw" / "nvic"
OCR_OUT = REPO / "data" / "ocr" / "nvic"
INDEX_JSON = RAW_NVIC / "index.json"

logger = logging.getLogger("ocr_nvic")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ── DB query helpers ──────────────────────────────────────────────────────

def fetch_db_nvic_ids() -> set[str]:
    """Pull distinct NVIC <num>-<yy> identifiers currently in the DB.

    Uses docker exec → psql so we don't need to import the api/asyncpg stack.
    """
    out = subprocess.check_output([
        "docker", "exec", "regknots-postgres", "psql",
        "-U", "regknots", "-d", "regknots", "-P", "pager=off", "-t", "-A",
        "-c", "SELECT DISTINCT section_number FROM regulations WHERE source = 'nvic'",
    ]).decode()
    ids: set[str] = set()
    for line in out.splitlines():
        m = re.match(r"^NVIC (\d+-\d+)", line)
        if m:
            ids.add(m.group(1))
    return ids


def fetch_index_ids() -> list[dict]:
    """Read the local USCG NVIC index.json (populated by the discovery
    phase of the regular nvic adapter)."""
    with INDEX_JSON.open() as f:
        return json.load(f)


# ── Triage: which NVICs need OCR? ─────────────────────────────────────────

def needs_ocr(pdf_path: Path) -> bool:
    """True if pdfplumber returns near-zero text from this PDF.

    Threshold: <300 chars across all pages = effectively no extractable
    text, almost certainly a scanned image. NVICs with body text yield
    thousands of chars even on the shortest documents.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total = sum(len(p.extract_text() or "") for p in pdf.pages)
        return total < 300
    except Exception as e:
        logger.warning("%s: pdfplumber error %s — flagging for OCR", pdf_path.name, e)
        return True


# ── Anthropic vision OCR ──────────────────────────────────────────────────

# Anthropic supports PDFs as document content blocks directly (no need to
# render to images locally). The model reads the PDF natively, including
# scanned page rasters via OCR internally.
ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"

OCR_SYSTEM_PROMPT = """You are extracting text from a scanned USCG Navigation and Vessel Inspection Circular (NVIC) PDF for regulatory reference ingest.

Your job is faithful transcription. Return ONLY the extracted text — no preamble, no commentary, no markdown formatting beyond what the original document contains.

Rules:
- Preserve the document's section numbering and hierarchy. NVICs typically have numbered sections like "1.", "2.", etc. with sub-sections "1.a.", "1.b.", and so on. Keep all numbering intact.
- Reproduce headings as they appear (caps, layout).
- Skip page numbers, headers, and footers that repeat across pages.
- Skip USCG letterhead and signature blocks if they're at the top of every page.
- Output as plain text with line breaks. Do not add markdown headers or bold formatting.
- If a page is pure imagery (e.g., a chart or diagram) and contains no readable text, output a single line: "[FIGURE — no transcribable text]" and continue.
- The document may have multiple sections; extract them all in order.

Output the full transcribed text only. Begin extraction now."""


async def ocr_pdf(pdf_path: Path, api_key: str, http: httpx.AsyncClient) -> str:
    """Send the PDF to Anthropic's vision API and return extracted text."""
    pdf_bytes = pdf_path.read_bytes()
    pdf_b64 = base64.b64encode(pdf_bytes).decode()
    payload = {
        "model": ANTHROPIC_MODEL,
        "max_tokens": 8000,
        "system": OCR_SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": pdf_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            f"This is NVIC {pdf_path.stem}. Transcribe its text content "
                            f"following the rules in the system prompt. Output the text only."
                        ),
                    },
                ],
            }
        ],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = await http.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers,
        json=payload,
        timeout=300.0,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = [b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"]
    text = "".join(parts).strip()
    if not text:
        raise RuntimeError(f"empty response from Anthropic for {pdf_path.name}")
    return text


# ── Pipeline ──────────────────────────────────────────────────────────────


async def main(args: argparse.Namespace) -> int:
    OCR_OUT.mkdir(parents=True, exist_ok=True)
    api_key = _read_anthropic_api_key()
    if not api_key and not args.dry_run:
        logger.error("Could not read ANTHROPIC_API_KEY from env or .env. Aborting.")
        return 2

    db_ids = fetch_db_nvic_ids()
    index_entries = fetch_index_ids()
    logger.info("DB has %d NVIC IDs; index has %d", len(db_ids), len(index_entries))

    # Find missing NVICs whose PDFs need OCR.
    missing: list[tuple[str, Path]] = []
    for entry in index_entries:
        nid = entry["number"]
        if nid in db_ids:
            continue
        pdf = RAW_NVIC / f"{nid}.pdf"
        if not pdf.exists():
            logger.info("skip %s: PDF not on disk", nid)
            continue
        if not needs_ocr(pdf):
            logger.info("skip %s: pdfplumber extracts text fine — needs different fix, not OCR", nid)
            continue
        missing.append((nid, pdf))

    logger.info("identified %d NVICs needing OCR", len(missing))
    if args.dry_run:
        for nid, pdf in missing[:30]:
            print(f"  {nid}  ({pdf.stat().st_size:>8} bytes)")
        if len(missing) > 30:
            print(f"  ... and {len(missing) - 30} more")
        return 0

    # OCR pass.
    summary = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "model": ANTHROPIC_MODEL,
        "results": [],
    }
    successes = 0
    failures = 0
    async with httpx.AsyncClient() as http:
        for nid, pdf in missing:
            if args.limit and successes >= args.limit:
                logger.info("hit --limit %d, stopping", args.limit)
                break
            out_path = OCR_OUT / f"{nid}.txt"
            if out_path.exists() and not args.force:
                logger.info("%s: sidecar exists at %s, skipping (use --force)", nid, out_path)
                continue
            try:
                logger.info("OCRing %s …", nid)
                text = await ocr_pdf(pdf, api_key, http)
                out_path.write_text(text, encoding="utf-8")
                logger.info("%s: wrote %d chars", nid, len(text))
                summary["results"].append({"nid": nid, "ok": True, "chars": len(text)})
                successes += 1
            except Exception as exc:
                logger.warning("%s: OCR failed — %s", nid, exc)
                summary["results"].append({"nid": nid, "ok": False, "error": str(exc)[:200]})
                failures += 1

    summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    summary["successes"] = successes
    summary["failures"] = failures
    audit_path = OCR_OUT / "_summary.json"
    audit_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    logger.info("done: %d successes, %d failures. Audit: %s", successes, failures, audit_path)
    return 0 if failures == 0 else 1


def _read_anthropic_api_key() -> str | None:
    """Read ANTHROPIC_API_KEY from env or /opt/RegKnots/.env."""
    import os
    if k := os.environ.get("ANTHROPIC_API_KEY"):
        return k
    env_path = REPO / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="list targets, don't call API")
    parser.add_argument("--limit", type=int, default=0, help="stop after N successes (0 = no limit)")
    parser.add_argument("--force", action="store_true", help="re-OCR even if sidecar exists")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args)))

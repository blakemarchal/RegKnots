"""OCR scanned PDFs with tesseract into the sidecar text files the adapters
read (2026-09-30).

  nvic                data/ocr/nvic/<number>.txt         (nvic.parse_source)
  uscg_cvc and the    data/ocr/<source>/<file stem>.txt  (uscg_docs.doc_sections)
  other uscg_docs
  listing sources

A document is a target when its PDF is on disk, has no text layer (less text
than the adapter needs) and has no sidecar yet. Each page is rendered with
pdftoppm at 300 dpi and read by tesseract (apt package tesseract-ocr, free and
local; the older data/ocr/nvic files came from Claude vision,
scripts/ocr_scanned_nvics.py). Pages are joined with form feeds, so
uscg_docs.clean_text can drop running heads; the NVIC parser ignores them.

Run on the VPS from packages/ingest, then re-ingest what it wrote:
  uv run python -m ingest.ocr --source nvic [--only 02-23] [--dry-run]
  uv run python -m ingest.ocr --source uscg_cvc [--dry-run]
  scripts/run_ingest.sh --source nvic --nvic 02-23 --nvic 10-02 ...
  scripts/run_ingest.sh --source uscg_cvc --update --no-notify
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from ingest.sources import uscg_docs as u

logger = logging.getLogger(__name__)

DATA = Path(__file__).resolve().parents[3] / "data"
DPI = 300
NVIC_MIN_CHARS = 200            # below this a PDF counts as a scan
LISTING_MIN_CHARS = 80          # uscg_docs.doc_sections' threshold


@dataclass
class Target:
    doc_id: str
    pdf: Path
    out: Path


def _first_pages_have_text(pdf: Path, min_chars: int) -> bool:
    """Fast screen: pdftotext on pages 1–3. A scan has no text there; only
    PDFs that fail it get the adapter's full (slow, pdfplumber) extraction."""
    try:
        res = subprocess.run(["pdftotext", "-f", "1", "-l", "3", str(pdf), "-"],
                             capture_output=True, text=True, timeout=60)
    except (subprocess.SubprocessError, OSError):
        return False
    return len(res.stdout.strip()) >= min_chars


def nvic_targets(raw_dir: Path, ocr_dir: Path, only: list[str] | None = None,
                 force: bool = False) -> list[Target]:
    entries = json.loads((raw_dir / "index.json").read_text(encoding="utf-8"))
    out: list[Target] = []
    for e in entries:
        number = e.get("number")
        if not number or (only and number not in only):
            continue
        pdf, txt = raw_dir / f"{number}.pdf", ocr_dir / f"{number}.txt"
        if not pdf.exists() or (txt.exists() and not force):
            continue
        if _first_pages_have_text(pdf, NVIC_MIN_CHARS):
            continue
        if len(u.pdf_text(pdf).strip()) < NVIC_MIN_CHARS:
            out.append(Target(f"NVIC {number}", pdf, txt))
    return out


def listing_targets(raw_dir: Path, ocr_dir: Path, only: list[str] | None = None,
                    force: bool = False) -> list[Target]:
    out: list[Target] = []
    for doc in u.read_index(raw_dir):
        if only and doc.doc_id not in only:
            continue
        pdf = raw_dir / doc.filename
        txt = ocr_dir / f"{pdf.stem}.txt"
        if pdf.suffix.lower() != ".pdf" or not pdf.exists() or (txt.exists() and not force):
            continue
        if _first_pages_have_text(pdf, LISTING_MIN_CHARS):
            continue
        if len(u.clean_text(u.pdf_text(pdf))) < LISTING_MIN_CHARS:
            out.append(Target(doc.doc_id, pdf, txt))
    return out


def _page_number(path: Path) -> int:
    m = re.search(r"-(\d+)\.png$", path.name)
    return int(m.group(1)) if m else 0


def ocr_pdf(pdf: Path, dpi: int = DPI) -> str:
    """The PDF's text, page by page, joined with form feeds."""
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}   # one core; the API keeps the other
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", str(dpi), "-gray", "-png", str(pdf), f"{tmp}/p"],
                       check=True, capture_output=True, timeout=600)
        pages = sorted(Path(tmp).glob("p-*.png"), key=_page_number)
        texts = []
        for page in pages:
            res = subprocess.run(["tesseract", str(page), "stdout", "-l", "eng", "--oem", "1", "--psm", "3"],
                                 check=True, capture_output=True, text=True, timeout=300, env=env)
            texts.append(res.stdout.rstrip() + "\n")
    return "\f".join(texts)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True, help="nvic, or a uscg_docs listing source (uscg_cvc, …)")
    ap.add_argument("--only", action="append", help="NVIC number or doc_id; repeatable")
    ap.add_argument("--dry-run", action="store_true", help="list the targets only")
    ap.add_argument("--force", action="store_true", help="OCR again even when a sidecar exists")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    raw_dir, ocr_dir = DATA / "raw" / args.source, DATA / "ocr" / args.source
    pick = nvic_targets if args.source == "nvic" else listing_targets
    targets = pick(raw_dir, ocr_dir, args.only, args.force)
    logger.info("%s: %d scanned PDFs without OCR text", args.source, len(targets))
    for t in targets:
        logger.info("  %s  %s", t.doc_id, t.pdf.name)
    if args.dry_run or not targets:
        return 0

    ocr_dir.mkdir(parents=True, exist_ok=True)
    summary = []
    for t in targets:
        start = time.monotonic()
        try:
            text = ocr_pdf(t.pdf)
        except (subprocess.SubprocessError, OSError) as exc:
            logger.warning("  %s: OCR failed — %s", t.doc_id, exc)
            summary.append({"doc_id": t.doc_id, "error": str(exc)[:200]})
            continue
        tmp = t.out.with_suffix(".txt.part")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(t.out)
        pages = text.count("\f") + 1
        logger.info("  %s: %d pages, %d chars, %.0f s -> %s", t.doc_id, pages, len(text),
                    time.monotonic() - start, t.out)
        summary.append({"doc_id": t.doc_id, "file": t.out.name, "pages": pages, "chars": len(text)})
    (ocr_dir / "_tesseract_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Singapore MPA (Maritime and Port Authority) Shipping Circulars +
Port Marine Circulars source adapter.

Sprint D6.22 — fourth-wave national-flag corpus expansion.

License posture: Singapore Crown copyright; no explicit open license.
Treat as public regulatory information for fair-use ingestion into a
private RAG knowledge base; surface attribution + source URL on cited
chunks.

Direct-PDF ingest from www.mpa.gov.sg/docs/mpalibraries/circulars-and-notices/
on a deterministic per-circular-number URL with sfvrsn cache-buster.

Section numbering convention:
  section_number = "MPA SC X/YYYY"     for shipping circulars
                 = "MPA PC X/YYYY"     for port marine circulars
  parent_section_number = "MPA Singapore"
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE       = "mpa_sc"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class CircularMeta:
    code:           str    # "SC 11/2025", "PC 04/2026"
    title:          str
    pdf_url:        str
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"MPA {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "MPA Singapore"

    @property
    def filename_stub(self) -> str:
        return "mpa_" + self.code.replace(" ", "_").replace("/", "-")


_BASE = "https://www.mpa.gov.sg/docs/mpalibraries/circulars-and-notices"

_CURATED: list[CircularMeta] = [
    # ── Shipping Circulars (flag-state guidance) ─────────────────────────────
    CircularMeta("SC 1/2026", "Reissue/consolidation (supersedes SC 21/2017)",
                 f"{_BASE}/sc_no_1_of_2026.pdf?sfvrsn=a7637d01_1",
                 date(2026, 1, 1), "consolidation"),
    CircularMeta("SC 4/2026", "Navigation safety advisory",
                 f"{_BASE}/sc_no_4_of_2026.pdf?sfvrsn=494b4fa5_1",
                 date(2026, 1, 1), "navigation"),
    CircularMeta("SC 8/2025", "Safety advisory — China coastal waters",
                 f"{_BASE}/sc_no_8_of_2025.pdf?sfvrsn=70b530ff_1",
                 date(2025, 1, 1), "safety_advisory"),
    CircularMeta("SC 10/2025", "RO-issued dispensations for SG-registered ships",
                 f"{_BASE}/sc_no_10_of_2025e819d0ae-e569-4c37-b196-f193ac1618cc.pdf?sfvrsn=38dcf8bd_1",
                 date(2025, 12, 1), "certification"),
    CircularMeta("SC 11/2025", "Merchant Shipping (Safety Convention) (Amdt) Regs 2025 + MARPOL Amdt",
                 f"{_BASE}/sc_no_11_of_2025.pdf?sfvrsn=f9ae7c09_1",
                 date(2026, 1, 1), "solas_marpol"),
    CircularMeta("SC 4/2024", "MEPC resolutions adoption",
                 f"{_BASE}/shipping-circular-no-04-of-2024--resolutions-adopted-by-mepc-8154dcc986-049d-4b75-8ada-3c1ff7c14350.pdf?sfvrsn=9a75b964_1",
                 date(2024, 1, 1), "marpol"),
    CircularMeta("SC 7/2024", "Flag-state guidance",
                 f"{_BASE}/sc_no_7_of_2024.pdf?sfvrsn=518aa214_1",
                 date(2024, 1, 1), "flag_state"),
    # ── Port Marine Circulars (port-state operations) ────────────────────────
    CircularMeta("PC 01/2026", "Annual list of active Port Marine Circulars",
                 f"{_BASE}/pc26-01.pdf?sfvrsn=3aa193b1_1",
                 date(2026, 1, 1), "meta_index"),
    CircularMeta("PC 04/2026", "E-vaporisers in port",
                 f"{_BASE}/pc26-04.pdf?sfvrsn=796db7ad_1",
                 date(2026, 1, 1), "port_ops"),
    CircularMeta("PMN 147/2025", "Anchoring at Changi East Deposition Area (CEDA)",
                 f"{_BASE}/pmn-147-of-2025---anchoring-of-vessels-at-changi-east-deposition-area-(ceda).pdf?sfvrsn=165ce2d8_1",
                 date(2025, 11, 20), "anchorage"),
    CircularMeta("PMN 170/2025", "Anchorage / works notice",
                 f"{_BASE}/pn25-170.pdf?sfvrsn=6f64e80e_1",
                 date(2026, 1, 1), "anchorage"),
]


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                console.print(f"  Downloading {meta.section_number} ({i}/{len(_CURATED)})…")
                resp = client.get(meta.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
                out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("MPA %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "effective_date": m.effective_date.isoformat(), "category": m.category}
            for m in _CURATED
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"MPA index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = CircularMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            effective_date=date.fromisoformat(e["effective_date"]),
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("MPA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("MPA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("MPA %s: text too short (%d), skipping", meta.section_number, len(text))
            continue
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=meta.section_number,
            section_title=meta.title,
            full_text=text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=meta.parent_section_number,
            published_date=meta.effective_date,
        ))
    logger.info("MPA: parsed %d sections from %d circular(s)", len(sections), len(entries))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal ─────────────────────────────────────────────────────────────────

def _extract_pdf_text(pdf_path: Path) -> str:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


def _write_failure(meta: CircularMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"mpa_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

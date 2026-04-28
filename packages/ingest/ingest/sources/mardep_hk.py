"""
Hong Kong Marine Department — Merchant Shipping Information Notes (MSINs).

Sprint D6.22.

License posture: HKSAR government copyright; no explicit open license.
Standard fair-use posture for public regulatory notices.

Direct-PDF ingest from www.mardep.gov.hk/filemanager/en/share/msnote/pdf/
on a deterministic per-MSIN URL: msinYYNN.pdf.

Section numbering convention:
  section_number = "HKMD MSIN YYYY/N"     (e.g. "HKMD MSIN 2025/36")
  parent_section_number = "HK Marine Department"
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


SOURCE       = "mardep_msin"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_BASE = "https://www.mardep.gov.hk/filemanager/en/share/msnote/pdf"
_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-HK,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class MSINMeta:
    code:           str    # "2025/36" (year/number)
    title:          str
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"HKMD MSIN {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "HK Marine Department"

    @property
    def filename_stub(self) -> str:
        return "hkmd_msin_" + self.code.replace("/", "_")

    @property
    def pdf_url(self) -> str:
        # msinYYNN.pdf where YY = 2-digit year, NN = 2-digit number
        year, num = self.code.split("/")
        yy = year[-2:]
        nn = num.zfill(2)
        return f"{_BASE}/msin{yy}{nn}.pdf"


_CURATED: list[MSINMeta] = [
    MSINMeta("2026/1",  "Annual flag-state notice (new-year opener)",
             date(2026, 1, 1), "annual"),
    MSINMeta("2025/36", "Grain/FSS/Polar/SOLAS II-1/II-2/V/VI/XIV Amdt Regs EIF",
             date(2026, 1, 1), "solas"),
    MSINMeta("2025/43", "MSC.1/Circ.1694 unified interpretations",
             date(2025, 7, 4), "solas"),
    MSINMeta("2025/28", "Interim guidelines — ammonia as fuel",
             date(2025, 1, 1), "alt_fuel"),
    MSINMeta("2025/14", "BWM.2/Circ.80 Rev.1 — ballast water guidance",
             date(2025, 1, 1), "bwm"),
    MSINMeta("2025/13", "2024 BMP — Best Management Practices anti-piracy",
             date(2025, 1, 1), "security"),
    MSINMeta("2024/68", "IMDG Code amendments",
             date(2024, 1, 1), "dangerous_goods"),
    MSINMeta("2024/70", "New Ballast Water Record Book — Res MEPC.369(80)",
             date(2025, 2, 1), "bwm"),
    MSINMeta("2024/5",  "Ballast water record-keeping & reporting",
             date(2024, 1, 1), "bwm"),
    MSINMeta("2024/4",  "MEPC 80 outputs — BWM Convention amdts EIF",
             date(2025, 2, 1), "bwm"),
    MSINMeta("2024/7",  "BWM.2/Circ.66 Rev.5",
             date(2024, 1, 1), "bwm"),
    MSINMeta("2024/42", "Fire Safety Systems (FSS) Code amdts",
             date(2024, 1, 1), "fire"),
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
                logger.warning("HKMD %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title,
             "effective_date": m.effective_date.isoformat(), "category": m.category}
            for m in _CURATED
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"HKMD index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = MSINMeta(
            code=e["code"], title=e["title"],
            effective_date=date.fromisoformat(e["effective_date"]),
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("HKMD %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("HKMD %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("HKMD %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("HKMD: parsed %d sections from %d MSIN(s)", len(sections), len(entries))
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


def _write_failure(meta: MSINMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"hkmd_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

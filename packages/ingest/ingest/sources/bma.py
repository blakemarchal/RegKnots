"""
Bahamas Maritime Authority (BMA) — Marine Notices.

Sprint D6.22 — Bahamas is a top-10 open registry by gross tonnage.

License posture: standard copyright; treat like LISCR / IRI as fair-use
ingestion of public regulatory notices for a private RAG knowledge
base; surface attribution + source URL on cited chunks.

Direct-PDF ingest from www.bahamasmaritime.com/wp-content/uploads/<year>-<mo>/
on a deterministic per-MN URL.

Section numbering convention:
  section_number = "BMA MN<NNN>"     (e.g. "BMA MN108")
  parent_section_number = "BMA Marine Notices"
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


SOURCE       = "bma_mn"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class MNMeta:
    code:           str    # "MN108", "MN082"
    title:          str
    pdf_url:        str
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"BMA {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "BMA Marine Notices"

    @property
    def filename_stub(self) -> str:
        return f"bma_{self.code.lower()}"


_BASE = "https://www.bahamasmaritime.com/wp-content/uploads"

_CURATED: list[MNMeta] = [
    MNMeta("MN108", "Hatches, Lifting Appliances and Anchor Handling Winches",
           f"{_BASE}/2025/12/MN108-Hatches-Lifting-Appliances-and-Anchor-Handling-Winches.pdf",
           date(2025, 12, 10), "cargo_gear"),
    MNMeta("MN085", "Carriage of Immersion Suits",
           f"{_BASE}/2025/11/MN085-Carriage-of-Immersion-Suits.pdf",
           date(2025, 11, 21), "lifesaving"),
    MNMeta("MN082", "Lifeboat Safety",
           f"{_BASE}/2023/10/MN082-Lifeboat-Safety.pdf",
           date(2023, 10, 30), "lifesaving"),
    MNMeta("MN079", "Firefighting Equipment",
           f"{_BASE}/2025/11/MN079-Firefighting-Equipment-1.pdf",
           date(2025, 11, 21), "fire"),
    MNMeta("MN065", "Ballast Water Management Convention",
           f"{_BASE}/2025/08/MN065-BWM.pdf",
           date(2025, 8, 26), "bwm"),
    MNMeta("MN020", "Training and Certification Requirements",
           f"{_BASE}/2025/11/MN020-Training-and-Certification-Requirements.pdf",
           date(2025, 11, 21), "stcw"),
    # The PDFs below have less-deterministic filenames; we attempt the
    # common pattern but failures are tolerable.
    MNMeta("MN018", "Safe Manning Requirements",
           f"{_BASE}/2022/05/MN018-Safe-Manning-Requirements.pdf",
           date(2022, 5, 9), "manning"),
    MNMeta("MN081", "Emergency Escape Breathing Devices (EEBDs)",
           f"{_BASE}/2023/01/MN081-EEBDs.pdf",
           date(2023, 1, 31), "fire"),
    MNMeta("MN080", "Inspection and Testing of Automatic Sprinkler Systems",
           f"{_BASE}/2023/11/MN080-Sprinklers.pdf",
           date(2023, 11, 29), "fire"),
    MNMeta("MN078", "Passenger Ship Watertight Doors",
           f"{_BASE}/2022/03/MN078-WTD.pdf",
           date(2022, 3, 14), "stability"),
    MNMeta("MN062", "MARPOL Annex VI Fuel Oil Sulphur Limit",
           f"{_BASE}/2022/05/MN062-MARPOL-Annex-VI.pdf",
           date(2022, 5, 4), "marpol"),
    MNMeta("MN060", "MARPOL Annex V",
           f"{_BASE}/2022/03/MN060-MARPOL-Annex-V.pdf",
           date(2022, 3, 14), "marpol"),
    MNMeta("MN059", "MARPOL Annex IV — Sewage",
           f"{_BASE}/2022/02/MN059-MARPOL-Annex-IV.pdf",
           date(2022, 2, 2), "marpol"),
    MNMeta("MN056", "MARPOL Oil Record Books",
           f"{_BASE}/2022/04/MN056-Oil-Record-Books.pdf",
           date(2022, 4, 5), "marpol"),
    MNMeta("MN096", "Remote Statutory Surveys, Audits and Inspections",
           f"{_BASE}/2025/11/MN096-Remote-Surveys.pdf",
           date(2025, 11, 21), "survey"),
    MNMeta("MN083", "Lifeboat / Rescue Boat Maintenance & Release Gear",
           f"{_BASE}/2021/12/MN083-Lifeboat-Maintenance.pdf",
           date(2021, 12, 6), "lifesaving"),
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
                logger.warning("BMA %s: download failed — %s", meta.section_number, exc)
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
        raise FileNotFoundError(f"BMA index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = MNMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            effective_date=date.fromisoformat(e["effective_date"]),
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("BMA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("BMA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("BMA %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("BMA: parsed %d sections from %d notice(s)", len(sections), len(entries))
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


def _write_failure(meta: MNMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"bma_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

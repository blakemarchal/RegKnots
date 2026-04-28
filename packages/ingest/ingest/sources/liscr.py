"""
Liberian International Ship and Corporate Registry (LISCR) Marine
Notices source adapter.

Sprint D6.20 — Liberia is the world's largest open registry by gross
tonnage. LISCR Marine Notices are the flag-state's authoritative
implementation guidance for IMO conventions, with topic codes:

  ADM-x  — administrative
  FIR-x  — fire safety
  ISM-x  — ISM Code implementation
  ISP-x  — ISPS Code implementation
  MAN-x  — manning / watchkeeping
  MLC-x  — Maritime Labour Convention 2006
  PCS-x  — port-state control
  POL-x  — MARPOL implementation
  PSC-x  — PSC interactions
  RAD-x  — radio / GMDSS
  SAF-x  — safety / lifesaving / drills
  SEA-x  — STCW / certification
  TEC-x  — technical (IMDG, equipment)

License posture: standard copyright, no explicit redistribution
license. We treat these like the IMO conventions — public regulatory
content, ingested under fair-use-of-public-regulatory-information for
a private knowledge-base. When citing, the chat layer renders an
attribution string and a link to liscr.com.

Direct-PDF ingest: each notice has a deterministic URL on
www.liscr.com/marketing/liscr/media/liscr/online%20library/maritime/<code>.pdf
so the adapter just iterates the curated list and downloads.

Section numbering convention:
  section_number = "LISCR <CODE>"     e.g. "LISCR SAF-004"
  parent_section_number = "LISCR Marine Notices"
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


# ── Constants ────────────────────────────────────────────────────────────────

SOURCE       = "liscr_mn"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_BASE_URL = (
    "https://www.liscr.com/marketing/liscr/media/liscr/"
    "online%20library/maritime"
)
_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class NoticeMeta:
    code:           str             # "SAF-004"
    title:          str
    revision:       str             # "11/24"
    category:       str             # for filtering / debugging

    @property
    def section_number(self) -> str:
        return f"LISCR {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "LISCR Marine Notices"

    @property
    def filename_stub(self) -> str:
        return f"liscr_{self.code.lower()}"

    @property
    def url(self) -> str:
        return f"{_BASE_URL}/{self.code.lower()}.pdf"


# ── Curated phase-1 list ─────────────────────────────────────────────────────

_CURATED_NOTICES: list[NoticeMeta] = [
    # Drills / training / lifesaving
    NoticeMeta("SAF-001", "Lifesaving Equipment — General Requirements", "07/20", "lsa"),
    NoticeMeta("SAF-003", "Enclosed-Space Entry and Rescue Drills", "09/24", "drills"),
    NoticeMeta("SAF-004", "Lifeboat and Emergency Drills — Frequency, Content, Recordkeeping", "11/24", "drills"),
    NoticeMeta("SAF-005", "Survival Craft / Launching Appliance Testing and Servicing", "07/20", "lsa"),
    # Manning
    NoticeMeta("MAN-001", "Manning of Vessels and Principles of Watchkeeping", "11/22", "manning"),
    # ISM / ISPS
    NoticeMeta("ISM-001", "ISM Code and SOLAS Ch.IX Implementation for Liberian Flag", "07/24", "ism"),
    NoticeMeta("ISM-003", "Harmonized ISM/ISPS Audit Regime", "01/23", "ism_isps"),
    NoticeMeta("ISP-001", "ISPS Code Implementation", "10/21", "isps"),
    # Fire
    NoticeMeta("FIR-001", "Fire-Protection Systems and Appliances", "07/24", "fire"),
    # MARPOL / pollution
    NoticeMeta("POL-001", "MARPOL Implementation Umbrella Notice", "11/24", "marpol"),
    NoticeMeta("POL-005", "Ballast Water Management Plans", "05/24", "bwm"),
    NoticeMeta("POL-014", "BWM Convention Survey and Certification", "05/24", "bwm"),
    # Dangerous goods
    NoticeMeta("TEC-005", "IMDG Code and Medical Oxygen Cylinder Carriage", "02/25", "dangerous_goods"),
    # MLC
    NoticeMeta("MLC-001", "MLC 2006 Implementation, Inspection, Certification", "08/24", "mlc"),
    # STCW certification
    NoticeMeta("SEA-001", "STCW Examination System for Merchant Marine Personnel", "02/22", "stcw"),
    # PSC
    NoticeMeta("PSC-001", "Measures to Minimize PSC Detentions", "09/24", "psc"),
    # Radio / logbook
    NoticeMeta("RAD-008", "Ship Radio / GMDSS Logbook and Retention", "02/23", "radio_logbook"),
]


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir: Path, failed_dir: Path, console
) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED_NOTICES, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                logger.debug("LISCR %s: already present, skipping", meta.section_number)
                success += 1
                continue
            try:
                console.print(
                    f"  Downloading {meta.section_number} ({i}/{len(_CURATED_NOTICES)})…"
                )
                resp = client.get(meta.url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError(
                        f"Response is not a PDF (got {resp.content[:32]!r})"
                    )
                out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("LISCR %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED_NOTICES):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "code":     m.code,
                    "title":    m.title,
                    "revision": m.revision,
                    "category": m.category,
                }
                for m in _CURATED_NOTICES
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"LISCR index cache not found at {cache_path}. "
            "Run discovery first."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        meta = NoticeMeta(
            code=e["code"], title=e["title"],
            revision=e["revision"], category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("LISCR %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("LISCR %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning(
                "LISCR %s: extracted text too short (%d chars), skipping",
                meta.section_number, len(text),
            )
            continue
        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = meta.section_number,
            section_title         = meta.title,
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = meta.parent_section_number,
        ))
    logger.info("LISCR: parsed %d sections from %d notice(s)",
                len(sections), len(entries))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal helpers ─────────────────────────────────────────────────────────

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


def _write_failure(meta: NoticeMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url":            meta.url,
        "error":          f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"liscr_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

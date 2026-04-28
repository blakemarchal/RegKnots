"""
Republic of the Marshall Islands (RMI) / IRI Marine Notices source
adapter.

Sprint D6.20 — Marshall Islands is a top-3 open registry. IRI
(International Registries Inc.) administers the flag and publishes
Marine Notices identified by `MN-<series>-<num>` codes such as
MN-2-011-13 (ISM Code) or MN-7-038-2 (Safe Manning).

License posture: standard copyright per IRI Terms & Conditions
("Reproduction…other than for personal use…prohibited without prior
written consent"). Same posture as we use for IMO conventions and
LISCR notices: ingest under fair-use-of-public-regulatory-information
for a private knowledge-base, surface excerpts with attribution + a
link to register-iri.com on every cited chunk.

Direct-PDF ingest: every notice has a deterministic URL
`https://www.register-iri.com/wp-content/uploads/MN-<series>.pdf`.

Section numbering convention:
  section_number = "RMI MN-<code>"     e.g. "RMI MN-2-011-13"
  parent_section_number = "RMI Marine Notices"
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

SOURCE       = "iri_mn"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_BASE_URL   = "https://www.register-iri.com/wp-content/uploads"
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
    code:           str             # "2-011-13", "7-038-2"
    title:          str
    revision:       str             # "10/2023"
    category:       str

    @property
    def section_number(self) -> str:
        return f"RMI MN-{self.code}"

    @property
    def parent_section_number(self) -> str:
        return "RMI Marine Notices"

    @property
    def filename_stub(self) -> str:
        return f"iri_mn_{self.code.replace('-', '_')}"

    @property
    def url(self) -> str:
        return f"{_BASE_URL}/MN-{self.code}.pdf"


# ── Curated phase-1 list ─────────────────────────────────────────────────────

_CURATED_NOTICES: list[NoticeMeta] = [
    # Carriage / publications
    NoticeMeta("1-000-3", "Carriage of Publications on Board", "8/2025", "carriage"),
    # International instruments adopted by RMI
    NoticeMeta("2-011-1",  "International Maritime Conventions Adopted by RMI", "3/2023", "conventions"),
    # Dangerous goods (IMDG)
    NoticeMeta("2-011-2",  "IMDG Code and Medical Oxygen Cylinder Requirements", "3/2025", "dangerous_goods"),
    # ISM
    NoticeMeta("2-011-13", "International Safety Management (ISM) Code", "10/2023", "ism"),
    # Fire systems
    NoticeMeta("2-011-14", "Maintenance and Inspection of Fire Protection Systems and Appliances", "8/2025", "fire"),
    # ISPS
    NoticeMeta("2-011-16", "International Ship and Port Facility Security (ISPS) Code", "7/2025", "isps"),
    # CSR
    NoticeMeta("2-011-19", "Continuous Synopsis Record (CSR)", "3/2023", "documentation"),
    # LRIT
    NoticeMeta("2-011-25", "Long-Range Identification and Tracking of Ships", "12/2023", "navigation"),
    # LSA
    NoticeMeta("2-011-37", "Life-Saving Appliances and Systems", "12/2025", "lsa"),
    # Piracy / armed security
    NoticeMeta("2-011-39", "Piracy, Armed Robbery, and the Use of Armed Security", "4/2019", "security"),
    # BNWAS
    NoticeMeta("2-011-40", "Bridge Navigation Watch Alarm Systems", "1/2023", "navigation"),
    # MARPOL
    NoticeMeta("2-013-2",  "MARPOL Recordkeeping and Reporting Requirements", "11/2022", "marpol"),
    NoticeMeta("2-013-5",  "MARPOL Annex V — Prevention of Garbage Pollution", "3/2024", "marpol"),
    NoticeMeta("2-013-8",  "MARPOL Annex VI — Air Pollution Implementation", "9/2025", "marpol_air"),
    NoticeMeta("2-013-12", "MARPOL Annex VI Ch.4 — Carbon Intensity (CII)", "12/2025", "marpol_cii"),
    # Ballast water
    NoticeMeta("2-014-1",  "Ballast Water Management", "4/2025", "bwm"),
    # PSC pre-arrival
    NoticeMeta("5-034-5",  "US, Australia, China Pre-Arrival Requirements", "8/2025", "psc"),
    # Manning / watchkeeping
    NoticeMeta("7-038-2",  "Minimum Safe Manning Requirements for Vessels", "7/2024", "manning"),
    NoticeMeta("7-038-4",  "Principles of Watchkeeping", "10/2017", "watchkeeping"),
    # Enclosed spaces / pilot transfer
    NoticeMeta("7-041-1",  "Entering Enclosed Spaces — Safety Precautions", "1/2026", "enclosed_space"),
    NoticeMeta("7-041-3",  "Pilot Transfer Arrangements", "1/2023", "pilot"),
    NoticeMeta("7-041-5",  "Electronic Log Book Systems", "4/2025", "logbook"),
    NoticeMeta("7-041-6",  "Nautical Chart and ECDIS Carriage Requirements", "4/2023", "navigation"),
    NoticeMeta("7-047-2",  "Approval of Maritime Training Centers, Courses and Programs", "12/2021", "training"),
]


# ── Public API (mirrors LISCR adapter) ───────────────────────────────────────

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
                logger.debug("RMI %s: already present, skipping", meta.section_number)
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
                logger.warning("RMI %s: download failed — %s", meta.section_number, exc)
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
            f"RMI index cache not found at {cache_path}. Run discovery first."
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
            logger.warning("RMI %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("RMI %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning(
                "RMI %s: extracted text too short (%d chars), skipping",
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
    logger.info("RMI: parsed %d sections from %d notice(s)",
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
    (failed_dir / f"iri_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

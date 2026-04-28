"""
IACS Unified Requirements (URs) source adapter.

Sprint D6.23 — international classification-society reference standard.

License: IACS publishes URs publicly with reproduction permitted under
IACS PR 38 with attribution. ClassNK and other member-society mirrors
redistribute the same authoritative text under that license.

Authority tier: Tier 4 (domain technical reference standard, like ERG).
URs are authoritative within their class-survey domain but do not
override SOLAS/CFR for binding regulatory questions.

Direct PDFs from a mix of mirrors (iacs.s3.af-south-1.amazonaws.com,
classnk.or.jp, turkloydu.org, eagle.org/ABS, caspianlloyd.az) — IACS's
own iacs.org.uk pages 403 non-browser agents, but member societies
host the same PDFs under PR 38. Each entry was verified to start with
%PDF magic bytes during the D6.23 research pass.

Section numbering convention:
  section_number = "IACS UR S11"   (or "IACS UR Z10.1" / "IACS UR M53")
  parent_section_number = "IACS Unified Requirements"
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


SOURCE       = "iacs_ur"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    "RegKnots/1.0 (+https://regknots.com)"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class URMeta:
    code:           str    # "S11", "Z10.1", "M53"
    title:          str
    pdf_url:        str
    revision:       str
    category:       str    # series letter for filtering / debugging

    @property
    def section_number(self) -> str:
        return f"IACS UR {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "IACS Unified Requirements"

    @property
    def filename_stub(self) -> str:
        return "iacs_ur_" + self.code.replace(".", "_").lower()


# Verified URLs only. URs that didn't have a confirmable %PDF mirror
# during research are excluded — better to have 26 verified URs than
# 40 with broken links. Phase 2 can chase the missing ones via
# Playwright on iacs.org.uk.

_CURATED: list[URMeta] = [
    # ── UR S — hull / structural ─────────────────────────────────────────────
    URMeta("S11",  "Longitudinal Strength Standard",
           "https://eclass.uniwa.gr/modules/document/file.php/NAFP134/Presentations/UR_S11.pdf",
           "Rev.7", "S_hull"),
    URMeta("S21",  "Evaluation of Scantlings of Hatch Covers, Coamings & Closing Arrangements",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_s21_rev.6_jan_2023cln.pdf",
           "Rev.6 Jan 2023", "S_hull"),
    URMeta("S26",  "Strength and Securing of Small Hatches on Exposed Fore Deck",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_s26rev.5_may_2023ul.pdf",
           "Rev.5 May 2023", "S_hull"),
    URMeta("S31",  "Renewal Criteria for Side Shell Frames in Single-Side-Skin Bulk Carriers",
           "https://www.caspianlloyd.az/wp-content/uploads/senedler/S31.pdf",
           "Rev.4 May 2023", "S_hull"),
    # ── UR Z — surveys ──────────────────────────────────────────────────────
    URMeta("Z3",   "Periodical Survey of the Outside of the Ship's Bottom",
           "https://www.turkloydu.org/pdf-files/iacs-karar-ve-csr-degisimleri/iacs-es-gereklilikleri/UR_Z3_Rev8_TR_EN.pdf",
           "Rev.8", "Z_survey"),
    URMeta("Z7",   "Hull Classification Surveys",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur-z7-rev.29-corr.1-may-2024-ul.pdf",
           "Rev.29 Corr.1 May 2024", "Z_survey"),
    URMeta("Z7.1", "Hull Surveys of General Dry-Cargo Ships",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur-z7.1-rev.15-corr.1-may-2024-ul.pdf",
           "Rev.15 Corr.1 May 2024", "Z_survey"),
    URMeta("Z10.1", "Hull Surveys of Oil Tankers",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_z10.1_rev.25_feb_2023ul.pdf",
           "Rev.25 Feb 2023", "Z_survey"),
    URMeta("Z10.2", "Hull Surveys of Bulk Carriers",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_z10.2_rev.37_feb_2023ul.pdf",
           "Rev.37 Feb 2023", "Z_survey"),
    URMeta("Z10.4", "Hull Surveys of Double-Hull Oil Tankers",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_z10.4_rev.18_feb_2023ul.pdf",
           "Rev.18 Feb 2023", "Z_survey"),
    URMeta("Z10.5", "Hull Surveys of Double-Skin Bulk Carriers",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_z10.5_rev.20_feb_2023ul.pdf",
           "Rev.20 Feb 2023", "Z_survey"),
    URMeta("Z17",  "Procedural Requirements for Service Suppliers",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur-z17-rev.20nov.2024ul.pdf",
           "Rev.20 Nov 2024", "Z_survey"),
    URMeta("Z23",  "Hull Survey for New Construction",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_z23_rev.7_corr.2_may_2023ul.pdf",
           "Rev.7 Corr.2 May 2023", "Z_survey"),
    # ── UR M — machinery ────────────────────────────────────────────────────
    URMeta("M51",  "Factory Acceptance Test of Reciprocating IC Engines",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_m51_rev.5_apr_2025_cr.pdf",
           "Rev.5 Apr 2025", "M_machinery"),
    URMeta("M53",  "Calculation of Crankshafts for IC Engines",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_m53rev.5_may_2023ul.pdf",
           "Rev.5 May 2023", "M_machinery"),
    URMeta("M68",  "Dimensions of Propulsion Shafts and Permissible Torsional Vibration Stresses",
           "https://www.turkloydu.org/pdf-files/iacs-karar-ve-csr-degisimleri/iacs-es-gereklilikleri/UR_M68.pdf",
           "Rev.3 Feb 2021", "M_machinery"),
    URMeta("M71",  "Type Testing of Reciprocating IC Engines",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_m71_rev.1_apr_2025_cr.pdf",
           "Rev.1 Apr 2025", "M_machinery"),
    # ── UR E — electrical / cyber ───────────────────────────────────────────
    URMeta("E10",  "Test Specification for Type Approval",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_e10_rev.9_aug_2023_ul.pdf",
           "Rev.9 Aug 2023", "E_electrical"),
    URMeta("E22",  "On-Board Use and Application of Computer-Based Systems",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_e22_rev.3_june_2023_ul.pdf",
           "Rev.3 Jun 2023", "E_electrical"),
    URMeta("E26",  "Cyber Resilience of Ships",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_e26_rev.1_nov_2023_cr.pdf",
           "Rev.1 Nov 2023", "E_cyber"),
    URMeta("E27",  "Cyber Resilience of On-Board Systems and Equipment",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_e27_rev.1_sep_2023_cln.pdf",
           "Rev.1 Sep 2023", "E_cyber"),
    # ── UR A — anchoring / mooring ──────────────────────────────────────────
    URMeta("A1",   "Anchoring Equipment",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_a1_rev.8_june_2023_ul.pdf",
           "Rev.8 Jun 2023", "A_anchoring"),
    URMeta("A2",   "Shipboard Fittings & Hull Structures for Towing/Mooring",
           "https://iacs.s3.af-south-1.amazonaws.com/wp-content/uploads/2022/02/16083302/ura.pdf",
           "Rev.5", "A_anchoring"),
    URMeta("A3",   "Anchor Windlass Design and Testing",
           "https://iacs.s3.af-south-1.amazonaws.com/wp-content/uploads/2022/02/16090035/ur-a3rev1.pdf",
           "Rev.1", "A_anchoring"),
    # ── UR W — welding / materials ──────────────────────────────────────────
    URMeta("W11",  "Normal and Higher Strength Hull Structural Steels",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_w11_rev.10_sep_2025_cln.pdf",
           "Rev.10 Sep 2025", "W_materials"),
    URMeta("W22",  "Offshore Mooring Chain",
           "https://www.turkloydu.org/pdf-files/iacs-karar-ve-csr-degisimleri/iacs-es-gereklilikleri/UR_W22_Rev6_TR_EN.pdf",
           "Rev.6 Jun 2016", "W_materials"),
    URMeta("W26",  "Welding Consumables for Aluminium Alloys",
           "https://iacs.s3.af-south-1.amazonaws.com/wp-content/uploads/2022/05/18143308/ur-w26rev1.pdf",
           "Rev.1", "W_materials"),
    URMeta("W28",  "Welding Procedure Qualification Tests of Steels for Hull Construction",
           "https://www.classnk.or.jp/hp/pdf/info_service/iacs_ur_and_ui/ur_w28_rev.3_sep_2025_complete_revision.pdf",
           "Rev.3 Sep 2025", "W_materials"),
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
                logger.warning("IACS %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "revision": m.revision, "category": m.category}
            for m in _CURATED
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"IACS index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = URMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            revision=e["revision"], category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("IACS %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("IACS %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("IACS %s: text too short (%d), skipping", meta.section_number, len(text))
            continue
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=meta.section_number,
            section_title=meta.title,
            full_text=text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=meta.parent_section_number,
        ))
    logger.info("IACS: parsed %d sections from %d UR(s)", len(sections), len(entries))
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


def _write_failure(meta: URMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"iacs_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

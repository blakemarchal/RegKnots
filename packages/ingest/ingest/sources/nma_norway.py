"""
Norwegian Maritime Authority (Sjøfartsdirektoratet / NMA) circulars.

Sprint D6.23 — Norway is the first non-English-flag in our corpus, but
NMA publishes its operational circulars in English directly. So this
adapter is a normal English ingest (no translation pipeline needed) —
the translation pipeline lands separately for France/Germany/etc.

License: Norwegian Crown copyright. NMA explicitly publishes circulars
for compliance use; fair-use ingestion of public regulatory content
for a private RAG knowledge base.

Direct-PDF ingest from www.sdir.no/contentassets/<guid>/<filename>.pdf
on per-circular URLs verified via direct fetch in the D6.22 research.

Section numbering convention:
  section_number = "NMA RSR 8-2014" / "NMA RSV 9-2020" / "NMA SM 6-2009"
                   (preserves the NMA series prefix: RSR = regulation,
                    RSV = circular guidance, SM = safety message)
  parent_section_number = "NMA Norway"
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


SOURCE       = "nma_rsv"
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
class CircularMeta:
    code:           str    # "RSR 8-2014", "RSV 9-2020", "SM 6-2009"
    title:          str
    pdf_url:        str
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"NMA {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "NMA Norway"

    @property
    def filename_stub(self) -> str:
        return "nma_" + self.code.replace(" ", "_").replace("-", "_").lower()


_CURATED: list[CircularMeta] = [
    # ── Cyber / SMS ──────────────────────────────────────────────────────────
    CircularMeta("RSV 9-2020", "Maritime Cyber Risk Management in the ISM Code",
                 "https://www.sdir.no/contentassets/ddc094c5706d4fd19b403b7e563c4382/eng-rsv-09-2020-om-maritim-cyber-security.pdf",
                 date(2021, 1, 1), "ism_cyber"),
    CircularMeta("RSV 18-2022", "Requirement to Report Cyber Incidents",
                 "https://sdir.no/contentassets/14c2691d150a47d79ba7d7341380fb2b/eng-rsv---krav-til-innrapportering-av-digitale-hendelser.pdf",
                 date(2022, 8, 17), "ism_cyber"),
    # ── LSA ──────────────────────────────────────────────────────────────────
    CircularMeta("RSR 8-2014", "Regulations on Life-Saving Appliances on Ships",
                 "https://sdir.no/contentassets/48e3cbbccdfe45baae16e34c6fe67e71/rsr-08-2014-on-life-saving-appliances-on-ships.pdf",
                 date(2014, 9, 15), "lsa"),
    CircularMeta("SM 8-2014", "Re-certification of Inflatable Life-Saving Equipment",
                 "https://www.sdir.no/contentassets/247a8a0349ab4b0fb124cc207ec53026/safety-alert-08-2014.pdf",
                 date(2014, 10, 28), "lsa"),
    # ── Fire ─────────────────────────────────────────────────────────────────
    CircularMeta("RSR 7-2014", "Regulations on Fire Protection on Ships",
                 "https://sdir.no/contentassets/337a1957dd2b444cafd0b8ebddba7fac/rsr-07-2014-on-the-regulations-on-fire-protection-on-ships.pdf",
                 date(2014, 9, 15), "fire"),
    # ── STCW / training ──────────────────────────────────────────────────────
    CircularMeta("RSV 2-2008", "Instructions for STCW Reg. I/10 Endorsement Applications",
                 "https://www.sdir.no/contentassets/740502c5e1f24ecda2d8616c92204db5/rsv-02-2008-instructions-for-application-for-endorsement.pdf",
                 date(2008, 5, 1), "stcw"),
    # ── Small-vessel SMS ─────────────────────────────────────────────────────
    CircularMeta("RSR 17-2016", "Safety Management for Small Cargo, Passenger, Fishing Vessels",
                 "https://www.sdir.no/contentassets/65ce232fbf3e448aa46f7079a91432e1/eng-rsr-17-2016.pdf",
                 date(2016, 12, 16), "ism_small_vessel"),
    CircularMeta("RSR 1-2020", "Vessels <24 m Carrying ≤12 Passengers",
                 "https://www.sdir.no/contentassets/dcb27c32209b48dc9ebc2e825b772c48/eng12pax_rsr.docx_nb-no_en-gb-1.pdf",
                 date(2020, 2, 1), "small_passenger"),
    # ── MLC / accommodation ─────────────────────────────────────────────────
    CircularMeta("RSR 4-2017", "Accommodation, Recreational Facilities, Food & Catering",
                 "https://www.sdir.no/contentassets/8c15d4a1f38c41209eaa8741e5e83401/eng-rsr-04-2017.pdf",
                 date(2017, 5, 1), "mlc"),
    # ── Fishing vessel stability ─────────────────────────────────────────────
    CircularMeta("RSV 1-2020", "Stability on Fishing Vessels with RSW Tanks",
                 "https://sdir.no/contentassets/72bbc79632d5452b85a3d9ed9a1cb900/eng-rsv-1-2020-stabilitet-pa-fiskefartoy-med-rsw-lastetanker.pdf",
                 date(2020, 1, 7), "fishing_stability"),
    # ── Watchkeeping / safety messages ──────────────────────────────────────
    CircularMeta("SM 6-2009", "Grounding and Violation of Regulations (Fatigue/Lookout)",
                 "https://sdir.no/contentassets/3191ec244b3042dabc8c15245f36834a/sm-06-2009-grounding-and-violation-of-regulations.pdf",
                 date(2009, 8, 3), "watchkeeping"),
    # ── IGF / low-flashpoint fuels ──────────────────────────────────────────
    CircularMeta("RSR 18-2016", "IGF Code Implementation (Low-Flashpoint Fuels)",
                 "https://www.sdir.no/contentassets/9defabbb2a1248a19a97df3efc446507/eng-rsr-18-2016.pdf",
                 date(2017, 1, 1), "igf"),
    # ── Polar ───────────────────────────────────────────────────────────────
    CircularMeta("RSR 15-2016", "Polar Code Safety Measures for Ships in Polar Waters",
                 "https://sdir.no/contentassets/4161d74e8c274c5aaf7841b0fd3205c3/rsr-15-2016-polar-code.pdf",
                 date(2017, 1, 1), "polar"),
    # ── Port State Control ──────────────────────────────────────────────────
    CircularMeta("RSR 20-2014", "Regulations on Port State Control",
                 "https://sdir.no/contentassets/c2e6ffd68b074ef0aeceadd45be8d4af/eng-rsr-20-2014.pdf",
                 date(2014, 11, 24), "psc"),
    # ── Dangerous goods ─────────────────────────────────────────────────────
    CircularMeta("RSR 12-2023", "Dangerous Goods — IMDG/IGC Code Amendments",
                 "https://sdir.no/contentassets/85ce5ac6e40e4547a444b7e7adecc8e4/eng-rsr-12-2023---forskrift-om-endring-i-forskrift-om-farlig-last.pdf",
                 date(2024, 1, 1), "dangerous_goods"),
    # ── Industrial personnel ────────────────────────────────────────────────
    CircularMeta("RSV 10-2022", "Transport and Accommodation of Industrial Personnel",
                 "https://sdir.no/contentassets/92b0c873006547a583a2e18842b9468d/videreforing-av-rsv-17-2016-requirements-regarding-transport-and-accommodation-of-industrial-personnel-002.pdf",
                 date(2022, 5, 16), "industrial_personnel"),
    # ── BWM ─────────────────────────────────────────────────────────────────
    CircularMeta("RSR 15-2024", "Ballast Water Record Book Amendment (MEPC.369(80))",
                 "https://sdir.no/contentassets/a8734063fa9e45429fc4a7467c702f43/eng-forskrift-om-endring-av-vedlegg-ii-til-ballastvannkonvensjonen.pdf",
                 date(2025, 2, 1), "bwm"),
    # ── Casualty reporting ──────────────────────────────────────────────────
    CircularMeta("RSR 20-2012", "Marine Accidents and Obligation to Notify",
                 "https://sdir.no/contentassets/fd63a404f1a34cc39e71f1b7de14380c/rsr-20-2012-marine-accidents-and-obligation-to-notify.pdf",
                 date(2012, 11, 30), "casualty"),
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
                logger.warning("NMA %s: download failed — %s", meta.section_number, exc)
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
        raise FileNotFoundError(f"NMA index cache not found at {cache_path}")
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
            logger.warning("NMA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("NMA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("NMA %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("NMA: parsed %d sections from %d circular(s)", len(sections), len(entries))
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
    (failed_dir / f"nma_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

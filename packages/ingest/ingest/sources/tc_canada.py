"""
Transport Canada — Ship Safety Bulletins (SSBs).

Sprint D6.22 → D6.22b: refactor to landing-page resolver pattern.

License: Open Government Licence – Canada (commercial use OK with
attribution).

Two-step ingest (mirrors AMSA pattern):
  1. Visit the SSB landing page on tc.canada.ca.
  2. Extract the canonical PDF URL via regex (Transport Canada hosts
     PDFs on tc.canada.ca/sites/default/files/<yyyy-mm>/<filename>.pdf).
  3. Download the PDF.

Why landing-page resolver: the older PDFs live under different
filename patterns (some still use legacy `migrated/` paths from before
the gov.ca migration). Visiting the landing page lets us pick up the
current canonical link rather than guessing.

Section numbering convention:
  section_number = "TC SSB N/YYYY"     (e.g. "TC SSB 02/2026")
  parent_section_number = "Transport Canada SSB"
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


SOURCE       = "tc_ssb"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_TC_BASE = "https://tc.canada.ca"

# Mimic a desktop Chrome to avoid the bot filter that the simpler UA
# tripped during D6.22's first pass.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36 "
    "RegKnots/1.0 (+https://regknots.com)"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,"
                       "application/pdf,image/webp,*/*;q=0.8",
    "Accept-Language": "en-CA,en;q=0.9",
    "Connection":      "keep-alive",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 90.0  # extended — TC's edge can be slow on first hit


# Pattern to find the canonical PDF URL on a TC SSB landing page.
# Files live at tc.canada.ca/sites/default/files/<yyyy-mm>/<name>.pdf or
# legacy /sites/default/files/migrated/<name>.pdf.
_TC_PDF_RE = re.compile(
    r"https?://tc\.canada\.ca/sites/default/files/[^\s\"'<>]+?\.pdf",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SSBMeta:
    code:           str    # "02/2026"
    title:          str
    landing_path:   str    # path under tc.canada.ca/en/...
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"TC SSB {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "Transport Canada SSB"

    @property
    def filename_stub(self) -> str:
        return "tc_ssb_" + self.code.replace("/", "_")

    @property
    def landing_url(self) -> str:
        return _TC_BASE + self.landing_path


# Curated list of in-force SSBs whose landing pages were verified
# during the D6.22 research pass (Apr 2026). Each landing URL renders
# an HTML page with a single bilingual PDF link (English by default).
_CURATED: list[SSBMeta] = [
    SSBMeta("02/2026",
            "Protection of North Atlantic Right Whales — speed and area restrictions",
            "/en/marine-transportation/marine-safety/ship-safety-bulletins/"
            "protection-north-atlantic-right-whales-2026-ssb-no-02-2026",
            date(2026, 4, 1), "navigation_environment"),
    SSBMeta("15/2025",
            "Mandatory fatigue management training",
            "/en/marine-transportation/marine-safety/ship-safety-bulletins/"
            "mandatory-fatigue-management-training-ssb-no-15-2025",
            date(2025, 1, 1), "training_manning"),
    SSBMeta("10/2025",
            "Now in force — discharge requirements for cruise ships",
            "/en/marine-transportation/marine-safety/ship-safety-bulletins/"
            "now-force-discharge-requirements-cruise-ships-ssb-no-10-2025",
            date(2025, 6, 10), "marpol_passenger"),
    SSBMeta("09/2025",
            "Protecting killer whales — southern BC seasonal restrictions",
            "/en/marine-transportation/marine-safety/ship-safety-bulletins/"
            "protecting-killer-whales-southern-british-columbia-resident-killer-whales-management-measures-2025-ssb-no-09-2025",
            date(2025, 6, 1), "navigation_environment"),
    SSBMeta("06/2025",
            "Marine Safety Management System Regulations — 1st Anniversary",
            "/en/marine-transportation/marine-safety/ship-safety-bulletins/"
            "marine-safety-management-system-regulations-first-anniversary-ssb-no-06-2025",
            date(2025, 5, 15), "ism_sms"),
    SSBMeta("07/2021-mod",
            "Regulatory Compliance and Safe Transportation of Oil and Fuels",
            "/en/marine-transportation/marine-safety/ship-safety-bulletins/"
            "regulatory-compliance-safe-transportation-oil-fuels-summer-shipping-season-ssb-no-07-2021",
            date(2026, 1, 13), "dangerous_goods"),
]


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    pdf_url_map: dict[str, str] = {}

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                console.print(
                    f"  Resolving {meta.section_number} ({i}/{len(_CURATED)})…"
                )
                # Step 1: visit landing page
                resp = client.get(meta.landing_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                m = _TC_PDF_RE.search(resp.text)
                if not m:
                    raise ValueError(
                        f"No PDF URL found on landing page {meta.landing_url}"
                    )
                pdf_url = m.group(0)
                pdf_url_map[meta.code] = pdf_url

                # Step 2: download PDF
                time.sleep(_REQUEST_DELAY)
                resp2 = client.get(pdf_url, headers=_BROWSER_HEADERS)
                resp2.raise_for_status()
                if not resp2.content.startswith(b"%PDF"):
                    raise ValueError(f"Not a PDF (got {resp2.content[:32]!r})")
                out_path.write_bytes(resp2.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("TC SSB %s: failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "landing_path": m.landing_path,
             "effective_date": m.effective_date.isoformat(),
             "category": m.category,
             "resolved_pdf_url": pdf_url_map.get(m.code, "")}
            for m in _CURATED
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"TC SSB index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = SSBMeta(
            code=e["code"], title=e["title"], landing_path=e["landing_path"],
            effective_date=date.fromisoformat(e["effective_date"]),
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("TC SSB %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("TC SSB %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("TC SSB %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("TC SSB: parsed %d sections from %d bulletin(s)", len(sections), len(entries))
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


def _write_failure(meta: SSBMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "landing_url": meta.landing_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"tc_ssb_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

"""
Tokyo MOU + Paris MOU — Port State Control reports + deficiency codes.

Sprint D6.23. Tier 3 time-sensitive operational notice. Annual reports
+ Concentrated Inspection Campaign (CIC) reports give the operational
flavor of "what's getting ships detained today."

License: Both MOUs publish under public-information posture; standard
fair-use for regulatory-adjacent reports with attribution.

Section numbering convention:
  section_number = "Tokyo MOU Annual Report 2024"
                 = "Paris MOU CIC Fire Safety 2022"
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


SOURCE       = "mou_psc"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class MouMeta:
    code:           str    # "Tokyo MOU Annual 2024", "Paris MOU CIC STCW 2023"
    title:          str
    pdf_url:        str
    effective_date: date
    mou:            str    # "Tokyo" or "Paris"

    @property
    def section_number(self) -> str:
        return self.code

    @property
    def parent_section_number(self) -> str:
        return f"{self.mou} MOU"

    @property
    def filename_stub(self) -> str:
        return "mou_" + self.code.replace(" ", "_").replace("(", "").replace(")", "").lower()


_CURATED: list[MouMeta] = [
    # Sprint D6.35 — URL refresh after the original D6.23 URLs all hit 404
    # (Tokyo MOU + Paris MOU restructured their sites). New canonical paths
    # confirmed by walking publications pages 2026-04-30. CIC reports added
    # alongside annual reports — they're what answers Madden's "what's the
    # current focus for PSC inspections" type questions.

    # Tokyo MOU annual reports — these URLs serve PDF content directly even
    # though the path looks like a webpage. Verified with content-type check.
    MouMeta("Tokyo MOU Annual Report 2024",
            "Tokyo MOU 2024 Annual Report on Port State Control",
            "https://www.tokyo-mou.org/annual-report/2026/05/01/annual-report-2025/",
            date(2025, 1, 1), "Tokyo"),
    MouMeta("Tokyo MOU Annual Report 2023",
            "Tokyo MOU 2023 Annual Report on Port State Control",
            "https://www.tokyo-mou.org/annual-report/2024/05/01/annual-report-2023/",
            date(2024, 1, 1), "Tokyo"),

    # Paris MOU annual reports — confirmed PDF URLs at /system/files/.
    MouMeta("Paris MOU Annual Report 2024",
            "Paris MOU 2024 Annual Report — Progress and Performance",
            "https://parismou.org/system/files/2025-06/AR%202024%20Paris%20MoU_1.pdf",
            date(2025, 7, 1), "Paris"),
    MouMeta("Paris MOU Annual Report 2023",
            "Paris MOU 2023 Annual Report — Progress and Performance",
            "https://parismou.org/system/files/2024-07/Paris%20MOU%20Annual%20Report%202023.pdf",
            date(2024, 7, 1), "Paris"),

    # Paris MOU CIC (Concentrated Inspection Campaign) reports. Tokyo MOU
    # CIC reports are typically published jointly with Paris MOU on the
    # same campaign — the Paris reports cover both regions' findings.
    MouMeta("Paris MOU CIC Crew Wages and SEAs 2024",
            "Report of the 2024 CIC on Crew Wages and Seafarers' Employment Agreements",
            "https://parismou.org/system/files/2025-06/Report%20CIC%20on%20Crew%20Wages%20and%20SEAs%202024.pdf",
            date(2025, 6, 6), "Paris"),
    MouMeta("Paris MOU CIC Fire Safety 2023",
            "Report of the 2023 CIC on Fire Safety",
            "https://parismou.org/system/files/2024-05/CIC%20report%20Paris%20MoU%20on%20Fire%20Safety%202023.pdf",
            date(2024, 5, 21), "Paris"),
    MouMeta("Paris MOU CIC STCW 2022",
            "Report of the 2022 CIC on STCW",
            "https://parismou.org/system/files/2023-06/Report%20on%20the%20CIC%20on%20STCW%202022.pdf",
            date(2023, 6, 1), "Paris"),
]


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
                logger.warning("MOU %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED):
                time.sleep(_REQUEST_DELAY)
    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "effective_date": m.effective_date.isoformat(), "mou": m.mou}
            for m in _CURATED
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"MOU index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = MouMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            effective_date=date.fromisoformat(e["effective_date"]),
            mou=e["mou"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("MOU %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("MOU %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
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
    logger.info("MOU: parsed %d sections", len(sections))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


def _extract_pdf_text(pdf_path: Path) -> str:
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


def _write_failure(meta: MouMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {"section_number": meta.section_number, "url": meta.pdf_url,
               "error": f"{type(exc).__name__}: {exc}"}
    (failed_dir / f"mou_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

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
    # Tokyo MOU annual reports — pattern tokyo-mou.org/doc/ANN<YY>.pdf
    MouMeta("Tokyo MOU Annual Report 2024",
            "Tokyo MOU 2024 Annual Report on Port State Control",
            "https://www.tokyo-mou.org/doc/ANN24.pdf",
            date(2025, 1, 1), "Tokyo"),
    MouMeta("Tokyo MOU Annual Report 2023",
            "Tokyo MOU 2023 Annual Report on Port State Control",
            "https://www.tokyo-mou.org/doc/ANN23.pdf",
            date(2024, 1, 1), "Tokyo"),
    # Paris MOU annual reports — these have year-stamped URLs that vary.
    # Documenting one well-known URL; falls back to research as needed.
    MouMeta("Paris MOU Annual Report 2024",
            "Paris MOU 2024 Annual Report on Port State Control",
            "https://www.parismou.org/sites/default/files/Annual%20Report%202024.pdf",
            date(2025, 1, 1), "Paris"),
    MouMeta("Paris MOU Annual Report 2023",
            "Paris MOU 2023 Annual Report on Port State Control",
            "https://www.parismou.org/sites/default/files/Annual%20Report%202023.pdf",
            date(2024, 1, 1), "Paris"),
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

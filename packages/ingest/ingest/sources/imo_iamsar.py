"""
IAMSAR Manual Vol III (Mobile Facilities) — IMO/ICAO joint publication.

Sprint D6.23. Vol III is the shipboard reference for SAR procedures.
USCG hosts a free copy under the "carry-aboard" authorization.
Tier 4 (reference manual, like ERG).

License: IMO/ICAO joint copyright; Vol III specifically authorized for
free shipboard distribution. Fair-use ingest into a private RAG.
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


SOURCE       = "imo_iamsar"
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
_TIMEOUT = 60.0


@dataclass(frozen=True)
class IAMSARMeta:
    code:    str
    title:   str
    pdf_url: str

    @property
    def section_number(self) -> str:
        return f"IAMSAR {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "IAMSAR Manual"

    @property
    def filename_stub(self) -> str:
        return "iamsar_" + self.code.replace(" ", "_").replace(".", "_").lower()


_CURATED: list[IAMSARMeta] = [
    IAMSARMeta(
        code="Vol III",
        title="IAMSAR Manual Volume III — Mobile Facilities",
        pdf_url="https://www.dco.uscg.mil/Portals/9/CG-5R/nsfcc/IAMSAR_Volume_III_2019.pdf",
    ),
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
                logger.warning("IAMSAR %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([{"code": m.code, "title": m.title, "pdf_url": m.pdf_url} for m in _CURATED], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"IAMSAR index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = IAMSARMeta(code=e["code"], title=e["title"], pdf_url=e["pdf_url"])
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("IAMSAR %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("IAMSAR %s: extraction failed — %s", meta.section_number, exc)
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
        ))
    logger.info("IAMSAR: parsed %d sections", len(sections))
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


def _write_failure(meta: IAMSARMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {"section_number": meta.section_number, "url": meta.pdf_url,
               "error": f"{type(exc).__name__}: {exc}"}
    (failed_dir / f"iamsar_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

"""
Cyprus Shipping Deputy Ministry (DMS) Circulars — source adapter.

Sprint D6.97 (2026-05-22) — RegKnots' first Eastern Mediterranean
flag-state corpus. Cyprus is a top-10 flag by registered tonnage and
a major EU registry; their circulars are the operational supplement
to EU directives and Cyprus's primary maritime legislation.

License: Cyprus government publications are public-domain under
local copyright law; reproduction for reference is permitted.

Discovery path:
  1. /dms/en/documents/<year>/ — year archive page lists every
     circular PDF as a direct <a href>. Found 178+ English-named
     circulars across 2018-2023; Greek-named (ΥΦΥΝ-...) added from
     2024 onward are skipped in this phase since they're likely
     Greek-language-only.
  2. Each PDF lives at /media/sites/25/<year>/<month>/<filename>.pdf

The 2022 archive slug has an unusual "-2" suffix
(/dms/en/documents/2022-2/) — preserved in the curated year list.

Section numbering convention:
  section_number = "Cyprus DMS Circular N/YYYY"
  parent_section_number = "Cyprus Shipping Deputy Ministry"

For filenames that don't yield a clean N+YYYY pair we fall back to
using the filename stub.
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
from pypdf import PdfReader

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE       = "cy_dms"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 22)

_BASE = "https://www.gov.cy"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.0
_TIMEOUT       = 60.0

# Year archives. The 2022 slug uses "2022-2" not "2022".
_YEAR_ARCHIVES: list[str] = [
    "2018", "2019", "2020", "2021", "2022-2", "2023",
]

# Cyprus's PDF storage path. Anchored to the /media/sites/25/ prefix
# to avoid matching unrelated PDFs that might be on the page.
_PDF_URL_RE = re.compile(
    r"https?://www\.gov\.cy/media/sites/25/[^\s\"'<>]+?\.pdf",
    re.IGNORECASE,
)

# Skip Greek-named circulars in v1 — they're likely Greek-language
# only and would need separate handling.
_GREEK_FILENAME_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")


@dataclass(frozen=True)
class CyprusCircularMeta:
    number:        str   # "1", "10", "23" etc.
    year:          str   # "2018"-"2026"
    pdf_url:       str
    filename:      str

    @property
    def section_number(self) -> str:
        return f"Cyprus DMS Circular {self.number}/{self.year}"

    @property
    def parent_section_number(self) -> str:
        return "Cyprus Shipping Deputy Ministry"

    @property
    def filename_stub(self) -> str:
        return f"cy_dms_{self.year}_{self.number}"


def _parse_circular_meta(pdf_url: str) -> CyprusCircularMeta | None:
    """Extract circular number + year from a PDF URL.

    Filename patterns observed in 2018-2023 archives:
      "Circular-1-2022-2022-01-10-en.pdf"        → 1/2022
      "Circular-2021-01-2021-01-08-1.pdf"        → 1/2021 (year first then num)
      "Circular-2020-05-2020-03-11.pdf"          → 5/2020
      "1-2019-2019-01-07.pdf"                    → 1/2019
      "10-2018-2018-03-23.pdf"                   → 10/2018
      "8-20182018-02-27.pdf"                     → 8/2018 (concat typo)
      "15-2015-23-07-2015.pdf"                   → 15/2015 (old, DMY date)

    Greek-named files (ΥΦΥΝ-...) are skipped — return None.
    """
    fname = pdf_url.rsplit("/", 1)[-1]
    if _GREEK_FILENAME_RE.search(fname):
        return None
    stem = fname.rsplit(".", 1)[0]
    # "Circular-N-YYYY-..." (N is 1-3 digits, YYYY is 4)
    m = re.match(r"(?i)Circular-(\d{1,3})-(20\d{2})", stem)
    if m:
        return CyprusCircularMeta(
            number=m.group(1).lstrip("0") or m.group(1),
            year=m.group(2), pdf_url=pdf_url, filename=fname,
        )
    # "Circular-YYYY-NN-..." (year first then num)
    m = re.match(r"(?i)Circular-(20\d{2})-(\d{1,3})", stem)
    if m:
        return CyprusCircularMeta(
            number=m.group(2).lstrip("0") or m.group(2),
            year=m.group(1), pdf_url=pdf_url, filename=fname,
        )
    # "N-YYYY-..." or "N-YYYYYYYY-..." (with concatenated-year typo)
    m = re.match(r"^(\d{1,3})-(20\d{2})", stem)
    if m:
        return CyprusCircularMeta(
            number=m.group(1).lstrip("0") or m.group(1),
            year=m.group(2), pdf_url=pdf_url, filename=fname,
        )
    return None


def discover_and_download(
    raw_dir: Path, failed_dir: Path, console,
) -> tuple[int, int]:
    """Walk each year archive, regex-extract PDF URLs, download.

    Idempotent: pre-existing PDFs > 5 KB are kept.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    all_meta: list[CyprusCircularMeta] = []
    seen_urls: set[str] = set()

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for year_slug in _YEAR_ARCHIVES:
            url = f"{_BASE}/dms/en/documents/{year_slug}/"
            try:
                console.print(f"  Discovering Cyprus DMS year {year_slug}…")
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
                pdf_urls = sorted(set(_PDF_URL_RE.findall(resp.text)))
                console.print(f"    found {len(pdf_urls)} PDF refs")
                for pdf_url in pdf_urls:
                    if pdf_url in seen_urls:
                        continue
                    seen_urls.add(pdf_url)
                    meta = _parse_circular_meta(pdf_url)
                    if meta is None:
                        # Greek-named or unparseable; skip in v1.
                        continue
                    all_meta.append(meta)
            except Exception as exc:
                logger.warning("Cyprus year %s: %s", year_slug, exc)
                console.print(f"    [yellow]ERROR: {exc}[/yellow]")
            time.sleep(_REQUEST_DELAY)

        console.print(f"  Cyprus: {len(all_meta)} parseable circulars to fetch")

        for i, meta in enumerate(all_meta, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                time.sleep(_REQUEST_DELAY * 0.5)
                resp2 = client.get(meta.pdf_url, headers=_HEADERS)
                resp2.raise_for_status()
                if not resp2.content.startswith(b"%PDF"):
                    raise ValueError(f"not a PDF (got {resp2.content[:32]!r})")
                out_path.write_bytes(resp2.content)
                success += 1
                if i % 25 == 0:
                    console.print(f"    {i}/{len(all_meta)} downloaded…")
            except Exception as exc:
                failures += 1
                logger.warning(
                    "Cyprus %s: download failed — %s", meta.section_number, exc,
                )
                _write_failure(meta, exc, failed_dir)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "number":         m.number,
                    "year":           m.year,
                    "pdf_url":        m.pdf_url,
                    "filename":       m.filename,
                    "filename_stub":  m.filename_stub,
                }
                for m in all_meta
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all downloaded Cyprus DMS circular PDFs."""
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"Cyprus DMS index not found at {cache_path}. Run discovery first."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        meta = CyprusCircularMeta(
            number=e["number"], year=e["year"],
            pdf_url=e["pdf_url"], filename=e["filename"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning(
                "Cyprus %s: extraction failed — %s", meta.section_number, exc,
            )
            continue
        if not text.strip() or len(text) < 400:
            logger.warning(
                "Cyprus %s: text too short (%d chars)",
                meta.section_number, len(text),
            )
            continue
        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = meta.section_number,
            section_title         = f"Cyprus Shipping Deputy Ministry Circular {meta.number}/{meta.year}",
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = meta.parent_section_number,
        ))

    logger.info("Cyprus DMS: parsed %d sections from %d entries",
                len(sections), len(entries))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


def _extract_pdf_text(pdf_path: Path) -> str:
    page_texts: list[str] = []
    reader = PdfReader(str(pdf_path))
    for page in reader.pages:
        t = page.extract_text() or ""
        t = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", t)  # standalone page numbers
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


def _write_failure(
    meta: CyprusCircularMeta, exc: Exception, failed_dir: Path,
) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "pdf_url":        meta.pdf_url,
        "error":          f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )

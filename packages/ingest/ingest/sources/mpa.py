"""
Singapore MPA (Maritime and Port Authority) Shipping Circulars +
Port Marine Circulars source adapter.

Sprint D6.45 — full-series expansion via predictable PDF-URL enumeration
(replaces the original D6.22 11-entry hand-curated list).

License posture: Singapore Crown copyright; no explicit open license.
Treat as public regulatory information for fair-use ingestion into a
private RAG knowledge base; surface attribution + source URL on cited
chunks.

Discovery flow:
  MPA's listing pages and Sitefinity media-centre API are JS-rendered
  / 401-gated, but their PDF storage is on a predictable static path:
    /docs/mpalibraries/circulars-and-notices/
       sc_no_<N>_of_<YYYY>.pdf       — Shipping Circulars
       port-marine-circulars/pc<YY>-<NN>.pdf
                                     — Port Marine Circulars
  We brute-force HEAD-check the cartesian product of plausible YY/NN/
  N/YYYY ranges and download the 200s. ~1500 candidate URLs sweep,
  ~150-200 hits expected based on PMC 01/2026 master-index data.

Section numbering convention:
  section_number = "MPA SC X/YYYY"  for shipping circulars
                 = "MPA PC X/YYYY"  for port marine circulars
  parent_section_number = "MPA Singapore"
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


SOURCE       = "mpa_sc"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 1)

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "RegKnots/1.0 (+https://regknots.com)"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9",
}
_HEAD_DELAY     = 0.15   # seconds between HEAD requests
_GET_DELAY      = 0.3
_TIMEOUT        = 30.0
_MAX_PDF_BYTES  = 15 * 1024 * 1024   # skip > 15 MB (image-heavy charts)

_BASE = "https://www.mpa.gov.sg/docs/mpalibraries/circulars-and-notices"


@dataclass(frozen=True)
class CircularMeta:
    code:           str    # "SC 11/2025", "PC 04/2026"
    title:          str
    pdf_url:        str
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"MPA {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "MPA Singapore"

    @property
    def filename_stub(self) -> str:
        return "mpa_" + re.sub(r"[^a-z0-9]+", "_",
                               self.code.lower()).strip("_")


# ── URL enumeration ──────────────────────────────────────────────────────────

# Year/number ranges to sweep.
#  - PCs (Port Marine Circulars): MPA migrated their CDN folder layout
#    in early 2024. PCs 2022-2023 live under .../port-marine-circulars/,
#    PCs 2024-onward live at the root .../circulars-and-notices/. We
#    probe both paths and take whichever 200s.
#  - SCs (Shipping Circulars): consistently at the root since at least
#    2020. Older years 404 reliably so we narrow the sweep.
_PMC_YEARS = range(20, 27)   # 2020-2026 (older PCs aren't on the CDN)
_PMC_NUMS  = range(1, 51)
_SC_YEARS  = range(2020, 2027)
_SC_NUMS   = range(1, 41)


def _enumerate_pmc() -> list[tuple[str, CircularMeta]]:
    """Return (probe_url, meta) tuples — emit BOTH path variants per
    candidate so the HEAD sweep can find whichever exists."""
    out: list[tuple[str, CircularMeta]] = []
    for yy in _PMC_YEARS:
        year = 2000 + yy
        for nn in _PMC_NUMS:
            for sub in ("", "port-marine-circulars/"):
                url = f"{_BASE}/{sub}pc{yy:02d}-{nn:02d}.pdf"
                out.append((url, CircularMeta(
                    code=f"PC {nn:02d}/{year}",
                    title=f"Port Marine Circular {nn:02d} of {year}",
                    pdf_url=url,
                    effective_date=date(year, 1, 1),
                    category="port_marine_circular",
                )))
    return out


def _enumerate_sc() -> list[tuple[str, CircularMeta]]:
    out: list[tuple[str, CircularMeta]] = []
    for yyyy in _SC_YEARS:
        for n in _SC_NUMS:
            url = f"{_BASE}/sc_no_{n}_of_{yyyy}.pdf"
            out.append((url, CircularMeta(
                code=f"SC {n}/{yyyy}",
                title=f"Shipping Circular {n} of {yyyy}",
                pdf_url=url,
                effective_date=date(yyyy, 1, 1),
                category="shipping_circular",
            )))
    return out


def _candidate_urls() -> list[tuple[str, CircularMeta]]:
    return _enumerate_pmc() + _enumerate_sc()


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0

    candidates = _candidate_urls()
    console.print(f"  [cyan]MPA candidate URLs:[/cyan] {len(candidates)} (HEAD-sweeping…)")

    confirmed: list[CircularMeta] = []
    seen_codes: set[str] = set()
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, (probe_url, meta) in enumerate(candidates, 1):
            if meta.section_number in seen_codes:
                continue  # already confirmed via the alternate path
            try:
                r = client.head(probe_url, headers=_BROWSER_HEADERS)
                if r.status_code == 200:
                    ct = (r.headers.get("Content-Type") or "").lower()
                    cl = int(r.headers.get("Content-Length") or 0)
                    if "pdf" in ct or cl > 5 * 1024:
                        confirmed.append(meta)
                        seen_codes.add(meta.section_number)
            except Exception as exc:
                logger.debug("MPA HEAD failed %s: %s", probe_url, exc)
            if i % 250 == 0:
                console.print(
                    f"    sweep: {i}/{len(candidates)} "
                    f"({len(confirmed)} hits so far)…"
                )
            time.sleep(_HEAD_DELAY)

        console.print(
            f"  [cyan]MPA confirmed PDFs:[/cyan] "
            f"{len(confirmed)} (downloading…)"
        )

        for i, meta in enumerate(confirmed, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                if i == 1 or i == len(confirmed) or i % 25 == 0:
                    console.print(f"  Downloading {meta.section_number} ({i}/{len(confirmed)})…")
                resp = client.get(meta.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
                if len(resp.content) > _MAX_PDF_BYTES:
                    raise ValueError(f"PDF too large ({len(resp.content)/1e6:.1f} MB)")
                out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("MPA %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            time.sleep(_GET_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "effective_date": m.effective_date.isoformat(),
             "category": m.category}
            for m in confirmed
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"MPA index cache not found at {cache_path}")
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
            logger.warning("MPA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("MPA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("MPA %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("MPA: parsed %d sections from %d circular(s)", len(sections), len(entries))
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
    (failed_dir / f"mpa_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

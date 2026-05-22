"""
Australian federal maritime statutes — source adapter.

Sprint D6.97 AU sprint Phase 1c (2026-05-22) — completes the AU
regulatory picture started in Phases 1a (MO 500-series) and 1b (NSCV).
Where Marine Orders define operational certificates, NSCV defines the
technical standards those certificates require, and these statutes are
the underlying primary law that authorises both.

Two Acts:

  Navigation Act 2012 (series C2012A00128) — the principal AU statute
    for safety, security, and protection of the marine environment.
    Covers seafarer credentialing, vessel safety standards, operation
    of foreign vessels in Australian waters, and the "Regulated
    Australian Vessel" concept Julius asked about (Part 2, Division 1,
    s.15).

  Marine Safety (Domestic Commercial Vessel) National Law Act 2012
  (series C2012A00121) — sets up the National Law and AMSA's role as
    the National Regulator for DCVs. The Marine Order 500-series is
    made UNDER this Act. Schedule 1 contains the actual National Law
    provisions.

License: AU federal statutes are Crown copyright under the
Commonwealth of Australia, distributed freely by the Office of
Parliamentary Counsel via legislation.gov.au for educational and
informational use.

Discovery + download (parallels amsa.py):
  1. legislation.gov.au/<series_id>/latest/downloads — a plain HTML
     index page that exposes the consolidated-compilation PDF URL.
  2. Fetch the PDF, save as data/raw/au_statutes/<short_name>.pdf.

Section numbering convention:
  section_number = "Navigation Act 2012"
                 | "Marine Safety (DCV) National Law Act 2012"
  parent_section_number = "Australian Statutes"
"""

import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
# Same pypdf swap as bv.py — the AU consolidated statute PDFs are
# 5-10 MB each with extensive cross-references; pypdf is safer on
# the 1 GB cgroup memory cap than pdfplumber.
from pypdf import PdfReader

from ingest.models import Section

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

SOURCE       = "au_statutes"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 22)  # adapter publication date

_LEGIS_BASE = "https://www.legislation.gov.au"
_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0

# Same regex as amsa.py — legislation.gov.au PDF URL pattern. The
# /<id>/latest/downloads page exposes the consolidated PDF link in
# /text/original/pdf form.
_LEGIS_PDF_RE = re.compile(
    r"[^\s\"'<>]*?/text/original/pdf",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class StatuteMeta:
    series_id:      str   # "C2012A00128" or "C2012A00121"
    section_number: str   # human-readable identifier (used verbatim)
    section_title:  str   # one-line description
    filename_stub:  str   # disk-safe short name
    category:       str   # for filtering / debugging


# ── Curated list ────────────────────────────────────────────────────────────

_CURATED_STATUTES: list[StatuteMeta] = [
    StatuteMeta(
        series_id="C2012A00128",
        section_number="Navigation Act 2012",
        section_title="Navigation Act 2012 — Commonwealth of Australia",
        filename_stub="navigation_act_2012",
        category="navigation_act",
    ),
    StatuteMeta(
        series_id="C2012A00121",
        section_number="Marine Safety (DCV) National Law Act 2012",
        section_title=(
            "Marine Safety (Domestic Commercial Vessel) National Law Act 2012 — "
            "Commonwealth of Australia"
        ),
        filename_stub="msdcv_national_law_act_2012",
        category="dcv_national_law",
    ),
]


# ── Public API ───────────────────────────────────────────────────────────────


def discover_and_download(
    raw_dir: Path, failed_dir: Path, console,
) -> tuple[int, int]:
    """For each statute: fetch the legislation.gov.au /<id>/latest/downloads
    page → regex-extract PDF URL → fetch PDF → save to
    data/raw/au_statutes/<stub>.pdf.

    Idempotent: pre-existing PDFs > 5 KB are kept.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    pdf_url_map: dict[str, str] = {}

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED_STATUTES, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                logger.debug("%s: already present, skipping", meta.section_number)
                success += 1
                pdf_url_map[meta.series_id] = ""  # placeholder
                continue
            try:
                console.print(
                    f"  Resolving {meta.section_number} "
                    f"({i}/{len(_CURATED_STATUTES)})…"
                )
                downloads_url = f"{_LEGIS_BASE}/{meta.series_id}/latest/downloads"
                resp = client.get(downloads_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                m = _LEGIS_PDF_RE.search(resp.text)
                if not m:
                    raise ValueError(
                        f"No /text/original/pdf URL found on {downloads_url}"
                    )
                pdf_path_or_url = m.group(0)
                # The regex matches a relative path or absolute URL; build
                # an absolute URL if needed.
                if pdf_path_or_url.startswith("//"):
                    pdf_url = "https:" + pdf_path_or_url
                elif pdf_path_or_url.startswith("/"):
                    pdf_url = _LEGIS_BASE + pdf_path_or_url
                else:
                    pdf_url = pdf_path_or_url
                pdf_url_map[meta.series_id] = pdf_url

                time.sleep(_REQUEST_DELAY)
                resp2 = client.get(pdf_url, headers=_BROWSER_HEADERS)
                resp2.raise_for_status()
                if not resp2.content.startswith(b"%PDF"):
                    raise ValueError(
                        f"Response is not a PDF (got {resp2.content[:32]!r})"
                    )
                out_path.write_bytes(resp2.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("%s: failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED_STATUTES):
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "series_id":      m.series_id,
                    "section_number": m.section_number,
                    "section_title":  m.section_title,
                    "filename_stub":  m.filename_stub,
                    "category":       m.category,
                    "pdf_url":        pdf_url_map.get(m.series_id, ""),
                }
                for m in _CURATED_STATUTES
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all downloaded statute PDFs into Section objects."""
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"AU statutes index cache not found at {cache_path}. "
            "Run discovery first (discover_and_download)."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        in_path = raw_dir / f"{e['filename_stub']}.pdf"
        if not in_path.exists():
            logger.warning("AU statute %s: PDF missing, skipping", e["section_number"])
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning(
                "AU statute %s: extraction failed — %s", e["section_number"], exc,
            )
            continue
        if not text.strip() or len(text) < 500:
            logger.warning(
                "AU statute %s: extracted text too short (%d chars), skipping",
                e["section_number"], len(text),
            )
            continue
        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = e["section_number"],
            section_title         = e["section_title"],
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = "Australian Statutes",
        ))

    logger.info(
        "AU statutes: parsed %d sections from %d entry/entries",
        len(sections), len(entries),
    )
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal helpers ─────────────────────────────────────────────────────────


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract page-joined text from a consolidated AU statute PDF.

    Strips the standard OPC (Office of Parliamentary Counsel)
    compilation header + page-number footer that appears on every page.
    """
    page_texts: list[str] = []
    reader = PdfReader(str(pdf_path))
    for page in reader.pages:
        t = page.extract_text() or ""
        t = _PAGE_NUMBER_LINE.sub("", t)
        t = _AUTHORISED_VERSION_LINE.sub("", t)
        t = _OPC_HEADER_LINE.sub("", t)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
_AUTHORISED_VERSION_LINE = re.compile(
    r"(?im)^.*Authorised\s+Version.*$"
)
_OPC_HEADER_LINE = re.compile(
    r"(?im)^.*(?:Office of Parliamentary Counsel|Compilation No\.|Federal Register of Legislation).*$"
)


def _write_failure(meta: StatuteMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "series_id":      meta.series_id,
        "error":          f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"au_statutes_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )

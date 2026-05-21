"""
National Standard for Commercial Vessels (NSCV) source adapter.

Sprint D6.97 AU sprint phase 1b — AMSA's NSCV is the operational
standard that sits under the Marine Safety (DCV) National Law Act 2012.
Where the Marine Order 500-series defines *which* certificates a DCV
needs, the NSCV defines *what* design, construction, and equipment
those certificates require. For questions like "does my DCV need
ECDIS?" the binding instrument is NSCV Part C7C (Navigation
equipment), not any Marine Order.

License: Creative Commons Attribution 4.0 International (CC BY 4.0),
same as the Marine Orders adapter. Required attribution:
"© Australian Maritime Safety Authority".

Two-step retrieval (parallel to amsa.py):
  1. AMSA landing page (amsa.gov.au/vessels-operators/.../<slug>) —
     a short overview with a download link to the consolidated PDF.
  2. The PDF lives at /sites/default/files/<YYYY-MM>/<filename>.pdf.
     Filename pattern varies between Parts and editions — sometimes
     "NSCV-C7C-Edition-1.5-010925.pdf", sometimes "nscv-f2-ed-2.7-...";
     we discover the URL with a permissive regex rather than hardcode.

Section numbering convention:
  section_number = "NSCV Part <id>"        e.g. "NSCV Part C7C"
  parent_section_number = "AMSA NSCV"
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

SOURCE       = "nscv"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 21)  # adapter publication, not Part edition

_AMSA_BASE      = "https://www.amsa.gov.au"
_USER_AGENT     = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-AU,en;q=0.9",
}
_REQUEST_DELAY = 1.5  # respectful — gov.au is on AWS, multi-request crawl
_TIMEOUT       = 60.0

# Permissive NSCV PDF URL regex. AMSA's filename patterns vary by
# edition — sometimes "NSCV-C7C-Edition-1.5-010925.pdf", sometimes
# "nscv-f2-ed-2.7-february-2022-...pdf", sometimes "nscv-c2-draft.pdf".
# We match any /sites/default/files/... URL containing "nscv" and
# ending in .pdf. The landing-page heuristic then disambiguates main
# document vs amending instrument.
_NSCV_PDF_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?amsa\.gov\.au/sites/default/files/[^\s\"'<>]*?nscv[^\s\"'<>]*?\.pdf",
    re.IGNORECASE,
)
# Amending instruments + drafts are not the main consolidated text we
# want — filter them out. The regex above grabs every NSCV PDF; this
# filter keeps only canonical Part PDFs.
_AMENDMENT_PATTERNS = re.compile(
    r"(?:amending|amendment|misc[\.\-]?no|draft)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NscvPart:
    part_id:       str          # "B", "C7C", "F1A", "G"
    title:         str
    slug:          str          # path under /vessels-operators/national-standard-commercial-vessels-nscv/
    category:      str          # for filtering / debugging

    @property
    def section_number(self) -> str:
        return f"NSCV Part {self.part_id}"

    @property
    def parent_section_number(self) -> str:
        return "AMSA NSCV"

    @property
    def filename_stub(self) -> str:
        # "C7C" -> "c7c", "F1A" -> "f1a", "B" -> "b"
        return self.part_id.lower().replace(" ", "_")


# ── Curated phase-1 list ─────────────────────────────────────────────────────
# 23 Parts covering the full operational surface of the NSCV. Compared
# to amsa.py's MO list, this is the comprehensive starting set rather
# than a curated subset — the NSCV is small enough (~22 PDFs) that
# ingesting everything is cheaper than ongoing curation work.

_CURATED_PARTS: list[NscvPart] = [
    NscvPart("B",   "General requirements",
             "general-requirements-b", "foundation"),
    NscvPart("C1",  "Wheelhouse visibility, escape, accommodation and personal safety",
             "arrangement-accommodation-and-personal", "construction_safety"),
    NscvPart("C2",  "Watertight and weathertight integrity",
             "watertight-weathertight-integrity", "construction_safety"),
    NscvPart("C3",  "Construction",
             "construction-c3", "construction_safety"),
    NscvPart("C4",  "Fire safety",
             "fire-safety-c4", "fire"),
    NscvPart("C5A", "Machinery",
             "machinery-c5a", "machinery"),
    NscvPart("C5B", "Electrical",
             "electrical-c5b", "electrical"),
    NscvPart("C5C", "LPG systems for appliances",
             "lpg-systems-appliances-c5c", "gas_systems"),
    NscvPart("C5D", "LPG systems for engines",
             "lpg-systems-engines-c5d", "gas_systems"),
    NscvPart("C6A", "Intact stability requirements",
             "intact-stability-requirements-c6a", "stability"),
    NscvPart("C6B", "Buoyancy and stability after flooding",
             "buoyancy-and-stability-after-flooding", "stability"),
    NscvPart("C6C", "Stability tests and stability information",
             "stability-tests-and-stability", "stability"),
    NscvPart("C7A", "Safety equipment",
             "safety-equipment-c7a", "equipment"),
    NscvPart("C7B", "Communications equipment",
             "communications-equipment-c7b", "equipment"),
    # C7C is the high-value entry — this is the actual binding authority
    # for ECDIS / chart / radar carriage on DCVs that Marine Order 506
    # was incorrectly hallucinated as in the 2026-05-21 audit (MO 506
    # was repealed; nav equipment requirements live here).
    NscvPart("C7C", "Navigation equipment",
             "navigation-equipment-c7c", "equipment_navigation"),
    NscvPart("C7D", "Anchoring systems",
             "anchoring-systems-c7d", "equipment"),
    NscvPart("F1A", "General requirements for fast craft",
             "general-requirements-fast-craft-f1a", "fast_craft"),
    NscvPart("F1B", "Category F1 fast craft",
             "category-f1-fast-craft-f1b", "fast_craft"),
    NscvPart("F1C", "Category F2 fast craft",
             "category-f2-fast-craft-f1c", "fast_craft"),
    NscvPart("F2",  "Leisure craft",
             "leisure-craft-f2", "leisure"),
    NscvPart("F3",  "Novel vessels",
             "novel-vessels-f3", "novel"),
    NscvPart("F4",  "Special purpose vessels",
             "special-purpose-vessels-f4", "special_purpose"),
    NscvPart("G",   "Non-survey vessels",
             "non-survey-vessels-g", "non_survey"),
]


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir: Path, failed_dir: Path, console
) -> tuple[int, int]:
    """For each NSCV Part: visit AMSA landing page → discover PDF URL →
    fetch + save to data/raw/nscv/<part_id>.pdf.

    Idempotent: pre-existing PDFs > 5 KB are kept (re-runs don't
    redownload). The intermediate landing-page response is not
    cached — only the PDF binary plus an index.json sidecar.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    pdf_url_map: dict[str, str] = {}  # part_id → resolved PDF URL

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED_PARTS, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                logger.debug("NSCV %s: already present, skipping", meta.section_number)
                success += 1
                continue
            try:
                console.print(
                    f"  Resolving NSCV Part {meta.part_id} "
                    f"({i}/{len(_CURATED_PARTS)})…"
                )
                # Step 1: landing page → discover PDF URL
                landing_url = (
                    f"{_AMSA_BASE}/vessels-operators/"
                    f"national-standard-commercial-vessels-nscv/{meta.slug}"
                )
                resp = client.get(landing_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                pdf_url = _pick_main_pdf_url(resp.text, meta.part_id)
                if not pdf_url:
                    raise ValueError(
                        f"No main-document NSCV PDF URL found in {landing_url}"
                    )
                # Normalize //www.amsa.gov.au/... and /sites/... forms.
                if pdf_url.startswith("//"):
                    pdf_url = "https:" + pdf_url
                elif pdf_url.startswith("/"):
                    pdf_url = _AMSA_BASE + pdf_url
                pdf_url_map[meta.part_id] = pdf_url

                # Step 2: fetch the PDF
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
                logger.warning(
                    "NSCV %s: failed — %s", meta.section_number, exc,
                )
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED_PARTS):
                time.sleep(_REQUEST_DELAY)

    # Cache the index for parse_source.
    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "part_id":  m.part_id,
                    "title":    m.title,
                    "slug":     m.slug,
                    "category": m.category,
                    "pdf_url":  pdf_url_map.get(m.part_id, ""),
                }
                for m in _CURATED_PARTS
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all downloaded NSCV PDFs into Section objects."""
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"NSCV index cache not found at {cache_path}. "
            "Run discovery first (discover_and_download)."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        meta = NscvPart(
            part_id=e["part_id"],
            title=e["title"],
            slug=e["slug"],
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("NSCV %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("NSCV %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 500:
            logger.warning(
                "NSCV %s: extracted text too short (%d chars), skipping",
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

    logger.info(
        "NSCV: parsed %d sections from %d Part(s)", len(sections), len(entries),
    )
    return sections


def get_source_date(raw_dir: Path) -> date:
    """Phase 1 returns adapter SOURCE_DATE; per-Part edition tracking
    is a phase-2 enhancement.
    """
    return SOURCE_DATE


# ── Internal helpers ─────────────────────────────────────────────────────────

def _pick_main_pdf_url(html: str, part_id: str) -> str | None:
    """Pick the canonical main-document PDF URL out of all NSCV PDF links
    on a landing page. Filter out amending instruments and drafts.

    The heuristic prefers a URL whose filename mentions the Part ID
    (case-insensitive). If no Part-ID match exists, fall back to the
    first non-amending hit.
    """
    candidates = _NSCV_PDF_RE.findall(html)
    if not candidates:
        return None
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for u in candidates:
        if u not in seen:
            seen.add(u)
            ordered.append(u)
    # Drop amending / draft URLs.
    main = [u for u in ordered if not _AMENDMENT_PATTERNS.search(u)]
    if not main:
        # Pathological: page only had amendments. Fall back to the first
        # candidate so the operator can audit manually.
        return ordered[0]
    # Prefer the one whose filename contains the Part ID.
    pid = part_id.lower()
    for u in main:
        if pid in u.lower().rsplit("/", 1)[-1]:
            return u
    return main[0]


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract page-joined text from a consolidated NSCV PDF.

    AMSA NSCV PDFs have consistent metadata blocks (publication notice,
    headers, page numbers) — strip those and let the chunker handle
    paragraph splitting downstream.
    """
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            t = _HEADER_FOOTER_LINE.sub("", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
_HEADER_FOOTER_LINE = re.compile(
    r"(?im)^.*(?:National Standard for Commercial Vessels|"
    r"NSCV\s+Part\s+[A-Z0-9]+\s*[—–-]\s*[A-Za-z ]+|"
    r"Edition\s+\d+(?:\.\d+)?).*$"
)


def _write_failure(meta: NscvPart, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "slug":           meta.slug,
        "error":          f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"nscv_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )

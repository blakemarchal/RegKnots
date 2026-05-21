"""
Bureau Veritas Marine & Offshore — source adapter.

Sprint D6.97 class-society expansion (2026-05-21) — RegKnots' fourth
class-society corpus, after ABS MVR, Lloyd's Register, and IACS UR/PR.
BV classes ~12% of the world fleet by tonnage.

License: BV publishes their Rules publicly on marine-offshore.bureauveritas.com
with reproduction for individual reference permitted. Commercial
republication requires written consent. Our use is RAG context for a
maritime-compliance product — gray area but matches the posture for
ABS MVR + LR rules already shipped.

Two-step retrieval:
  1. BV landing page (marine-offshore.bureauveritas.com/<slug>) lists
     the document parts as direct PDF anchors.
  2. PDFs live on rulesexplorer-docs.bureauveritas.com on a CDN —
     direct download, no auth required. Filename pattern:
       /documents/<nr-lower>/<month>/<NR-num>-NR_<part>_<date>.pdf

Phase-1 inventory:

  NR467 — Rules for the Classification of Steel Ships. The flagship
    BV ruleset for commercial vessels >500 GT. Parts A-F:
      A — General requirements
      B — Hull and stability
      C — Machinery, electrical, automation, fire protection
      D — Service notations (cargo / passenger / tug / fishing / ...)
      E — Additional class notations
      F — Additional requirements
    Consolidated + MainChanges PDFs are also published but excluded —
    individual Parts are what users will cite.

  NR606 — Common Structural Rules for Bulk Carriers and Oil Tankers.
    This is BV's distribution of the IACS CSR (the same text every
    IACS member publishes). One consolidated PDF.

  Future NRs: NR396 (HSC), NR490 (Crew Boats), NR527 (Polar),
    NR584 (Azimuth Thrusters), NR620, NR681. Add in follow-up sprints.

Section numbering convention:
  section_number = "BV NR467 Pt.A"        # individual NR Part
                 | "BV NR606 (IACS CSR)"  # consolidated single-PDF NRs
  parent_section_number = "BV Rules"
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import httpx
import pdfplumber

from ingest.models import Section

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

SOURCE       = "bv"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 21)

_BV_BASE = "https://marine-offshore.bureauveritas.com"
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.0
_TIMEOUT       = 60.0
# BV PartA-F PDFs are 4-15 MB each; skip anything pathologically large
# (image-heavy reference manuals can exceed pdfplumber's memory comfort).
_MAX_PDF_BYTES = 20 * 1024 * 1024

# Direct PDF URL pattern on BV's CDN. Anchored to the specific subdomain
# + path structure so we don't grab unrelated PDFs that might also be on
# the landing page (general terms, brochures, etc.).
_BV_PDF_RE = re.compile(
    r"https?://rulesexplorer-docs\.bureauveritas\.com/documents/[^\s\"'<>]+?\.pdf",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NrPart:
    """One Part of an NR (NR467 has 6 Parts; NR606 has just 1 consolidated PDF)."""
    code:    str   # "PartA" | "PartB" | ... | "Consolidated"
    title:   str   # human-readable description (Hull / Machinery / etc.)


@dataclass(frozen=True)
class NrMeta:
    """One BV NR ruleset."""
    nr:          str                # "NR467" | "NR606"
    title:       str
    slug:        str                # path under marine-offshore.bureauveritas.com
    parts:       tuple[NrPart, ...]  # Parts to ingest; empty = use all PDFs on page
    source_key:  str = SOURCE       # output source — NR606 overrides to "iacs_csr"

    @property
    def filename_stub(self) -> str:
        return self.nr.lower()


# ── Curated phase-1 list ─────────────────────────────────────────────────────

# Empty `parts` tuple means: take whatever PDFs the landing page exposes
# under the rulesexplorer-docs URL pattern. NR606 is one consolidated
# PDF; NR467 publishes individual Parts.

_CURATED_NRS: list[NrMeta] = [
    NrMeta(
        nr="NR467",
        title="Rules for the Classification of Steel Ships",
        slug="/nr467-rules-classification-steel-ships",
        parts=(
            NrPart("PartA", "General"),
            NrPart("PartB", "Hull and stability"),
            NrPart("PartC", "Machinery, electrical, automation, fire protection"),
            NrPart("PartD", "Service notations"),
            NrPart("PartE", "Additional class notations"),
            NrPart("PartF", "Additional requirements"),
        ),
        source_key="bv",
    ),
    NrMeta(
        nr="NR606",
        title="Common Structural Rules for Bulk Carriers and Oil Tankers (IACS CSR)",
        slug="/common-structural-rules-bulk-carriers-and-oil-tankers",
        parts=(
            NrPart("Consolidated", "Consolidated CSR"),
        ),
        # NR606 IS the IACS CSR. The PDF text is identical to what every
        # other IACS member society publishes. Tag it as iacs_csr so users
        # searching for CSR find it under the international authority, not
        # under BV-specific content.
        source_key="iacs_csr",
    ),
]


# ── Public API ───────────────────────────────────────────────────────────────


def discover_and_download(
    raw_dir: Path, failed_dir: Path, console,
) -> tuple[int, int]:
    """For each NR: visit BV landing page → grep rulesexplorer-docs PDF
    URLs → for each requested Part, match the URL whose filename
    contains that Part code → fetch + save.

    Saves PDFs to data/raw/bv/<nr>_<part>.pdf.

    Idempotent: pre-existing PDFs >100 KB are kept.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    index_entries: list[dict] = []

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED_NRS, 1):
            console.print(
                f"  Resolving BV {meta.nr} "
                f"({meta.title[:50]}…) [{i}/{len(_CURATED_NRS)}]"
            )
            try:
                # Step 1: discover available PDF URLs from the landing page.
                landing_url = f"{_BV_BASE}{meta.slug}"
                resp = client.get(landing_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                all_pdfs = sorted(set(_BV_PDF_RE.findall(resp.text)))
                if not all_pdfs:
                    raise ValueError(f"No rulesexplorer-docs PDF URLs on {landing_url}")
            except Exception as exc:
                failures += len(meta.parts)
                logger.warning("BV %s landing failed: %s", meta.nr, exc)
                for part in meta.parts:
                    _write_failure(meta, part, exc, failed_dir)
                if i < len(_CURATED_NRS):
                    time.sleep(_REQUEST_DELAY)
                continue

            # Step 2: for each requested Part, match a PDF URL.
            for part in meta.parts:
                pdf_url = _pick_part_pdf(all_pdfs, meta.nr, part.code)
                out_path = raw_dir / f"{meta.filename_stub}_{part.code.lower()}.pdf"

                if pdf_url is None:
                    failures += 1
                    err = ValueError(
                        f"No PDF URL matching {meta.nr} {part.code} in {len(all_pdfs)} "
                        f"candidates on landing page"
                    )
                    logger.warning("BV %s %s: %s", meta.nr, part.code, err)
                    _write_failure(meta, part, err, failed_dir)
                    continue

                if out_path.exists() and out_path.stat().st_size > 100 * 1024:
                    logger.debug("BV %s %s: already present, skipping", meta.nr, part.code)
                    success += 1
                    index_entries.append({
                        "nr":         meta.nr,
                        "part_code":  part.code,
                        "part_title": part.title,
                        "source_key": meta.source_key,
                        "pdf_url":    pdf_url,
                    })
                    continue

                try:
                    time.sleep(_REQUEST_DELAY)
                    resp2 = client.get(pdf_url, headers=_BROWSER_HEADERS)
                    resp2.raise_for_status()
                    if not resp2.content.startswith(b"%PDF"):
                        raise ValueError(
                            f"Response is not a PDF (got {resp2.content[:32]!r})"
                        )
                    if len(resp2.content) > _MAX_PDF_BYTES:
                        raise ValueError(
                            f"PDF size {len(resp2.content):,} exceeds {_MAX_PDF_BYTES:,} cap"
                        )
                    out_path.write_bytes(resp2.content)
                    success += 1
                    index_entries.append({
                        "nr":         meta.nr,
                        "part_code":  part.code,
                        "part_title": part.title,
                        "source_key": meta.source_key,
                        "pdf_url":    pdf_url,
                    })
                except Exception as exc:
                    failures += 1
                    logger.warning("BV %s %s download failed: %s", meta.nr, part.code, exc)
                    _write_failure(meta, part, exc, failed_dir)

            if i < len(_CURATED_NRS):
                time.sleep(_REQUEST_DELAY)

    # Cache index for parse_source.
    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(index_entries, indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    """Parse all downloaded BV PDFs into Section objects.

    Reads the index.json sidecar to know which Parts to expect and
    what source_key each maps to (BV's own NRs → 'bv'; NR606 → 'iacs_csr').
    """
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"BV index cache not found at {cache_path}. "
            "Run discovery first (discover_and_download)."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        nr = e["nr"]
        part_code = e["part_code"]
        part_title = e["part_title"]
        source_key = e["source_key"]

        in_path = raw_dir / f"{nr.lower()}_{part_code.lower()}.pdf"
        if not in_path.exists():
            logger.warning("BV %s %s: PDF missing, skipping", nr, part_code)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("BV %s %s: extraction failed — %s", nr, part_code, exc)
            continue
        if not text.strip() or len(text) < 500:
            logger.warning(
                "BV %s %s: extracted text too short (%d chars), skipping",
                nr, part_code, len(text),
            )
            continue

        # Section numbering convention:
        #   "BV NR467 Pt.A"            for multi-Part NRs
        #   "BV NR606 (IACS CSR)"      for single-PDF aliases
        # The part_code "Consolidated" is the special marker we use for
        # NR606's single PDF; pick the human-readable label accordingly.
        if part_code.lower() == "consolidated":
            section_number = f"BV {nr} (IACS CSR)" if nr == "NR606" else f"BV {nr}"
        else:
            # "PartA" → "Pt.A", "PartB" → "Pt.B" etc.
            short = part_code.replace("Part", "Pt.")
            section_number = f"BV {nr} {short}"

        section_title = part_title

        sections.append(Section(
            source                = source_key,
            title_number          = TITLE_NUMBER,
            section_number        = section_number,
            section_title         = section_title,
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = "BV Rules" if source_key == SOURCE else "IACS CSR",
        ))

    logger.info(
        "BV: parsed %d sections from %d entry/entries", len(sections), len(entries),
    )
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal helpers ─────────────────────────────────────────────────────────


def _pick_part_pdf(pdf_urls: list[str], nr: str, part_code: str) -> str | None:
    """Pick the PDF URL for a specific NR Part.

    BV's filename convention is "<num>-NR_<PartCode>_<date>.pdf" — e.g.
    "467-NR_PartA_2026-01.pdf" for NR467 Part A, or "606-NR_2025-01.pdf"
    for a single-PDF NR.

    For multi-Part NRs we anchor on PartCode (PartA / PartB / ...).
    For single-PDF NRs (NR606), we pick the most recent dated file that
    isn't a MainChanges or Consolidated supplement.
    """
    nr_num = nr.replace("NR", "").lower()
    # Filter to URLs for THIS NR (path component).
    nr_urls = [u for u in pdf_urls if f"/{nr_num}/" in u.lower() or f"/nr{nr_num}/" in u.lower()]
    if not nr_urls:
        return None

    if part_code.lower() == "consolidated":
        # Drop MainChanges (separately useful but not the main text)
        # and any Consolidated supplement; pick the single canonical PDF.
        clean = [u for u in nr_urls if not re.search(r"MainChanges", u, re.IGNORECASE)]
        # Prefer URLs without "PartX" in the filename (i.e., the
        # consolidated single doc).
        clean = [u for u in clean if not re.search(r"Part[A-F]\b", u, re.IGNORECASE)]
        return clean[-1] if clean else nr_urls[-1]

    # Multi-Part: find URL whose filename contains the exact PartCode
    # (PartA / PartB etc.).
    target_re = re.compile(rf"[_-]{re.escape(part_code)}[_-]", re.IGNORECASE)
    matches = [u for u in nr_urls if target_re.search(u)]
    if not matches:
        return None
    # Pick the most-recent-looking one (lexicographic sort works on the
    # YYYY-MM date suffix BV uses).
    return sorted(matches)[-1]


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract page-joined text from a BV PDF.

    BV PDFs have consistent headers (NR identifier + Part code) and
    page-number footers — strip those before chunking downstream.
    """
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            t = _HEADER_LINE.sub("", t)
            t = re.sub(r"[ \t]+", " ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
# Match BV's standard header pattern e.g. "Bureau Veritas - Rules for
# the Classification of Steel Ships - NR467 - Part A - January 2026"
_HEADER_LINE = re.compile(
    r"(?im)^.*Bureau\s+Veritas\s*[—–-].*$"
)


def _write_failure(meta: NrMeta, part: NrPart, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "nr":        meta.nr,
        "part_code": part.code,
        "slug":      meta.slug,
        "error":     f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"bv_{meta.nr.lower()}_{part.code.lower()}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8",
    )

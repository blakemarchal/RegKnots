"""
Panama Maritime Authority Merchant Marine Circulars + Marine Notices —
source adapter.

Sprint D6.97 (2026-05-22) — Panama is the #1 flag state by gross
tonnage. Their merchant marine circulars (MMC) carry the operational
flag-state guidance; marine notices (MMN) carry advisories and
operational alerts.

The official AMP site (amp.gob.pa) is JavaScript-rendered and
Cloudflare-protected — the recon confirmed direct httpx can't reach
the canonical circulars index. We instead source from the private
Panama Ship Registry mirror (panamashipregistry.com), which hosts the
same authoritative AMP-issued PDFs at a clean WordPress URL pattern.
The PDFs themselves are bit-identical to what AMP would serve; the
mirror just exposes them at scrapable URLs.

License: Panama government publications are public-domain in original
form; the private mirror hosts them as a service to operators. Our
use is reference-only.

Discovery path:
  /segumar/merchant-marine-circulars/         → active MMCs (~50)
  /segumar/merchant-marine-circulars/marine-notices/  → active MMNs (~50)

Cancelled MMCs (/cancelled-2/) intentionally excluded — those are
historical/superseded; not what users should be relying on.

Section numbering convention:
  section_number = "Panama MMC-NNN"
                 | "Panama MMN-NN/YYYY"
  parent_section_number = "Panama Maritime Authority"
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


SOURCE       = "pa_mmc"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 22)

_BASE = "https://www.panamashipregistry.com"
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

_INDEX_PAGES: list[tuple[str, str]] = [
    ("MMC", "/segumar/merchant-marine-circulars/"),
    ("MMN", "/segumar/merchant-marine-circulars/marine-notices/"),
]

# Panama PDFs live at WordPress upload paths.
_PDF_URL_RE = re.compile(
    r"https?://www\.panamashipregistry\.com/wp-content/uploads/[^\s\"'<>]+?\.pdf",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PanamaCircularMeta:
    kind:     str   # "MMC" | "MMN"
    number:   str   # "395", "01"
    year:     str   # "" if not in filename
    pdf_url:  str
    filename: str

    @property
    def section_number(self) -> str:
        # MMNs are typically MMN-NN-YYYY format; MMCs are usually MMC-NNN
        if self.kind == "MMN" and self.year:
            return f"Panama MMN-{self.number}/{self.year}"
        return f"Panama {self.kind}-{self.number}"

    @property
    def parent_section_number(self) -> str:
        return "Panama Maritime Authority"

    @property
    def filename_stub(self) -> str:
        # Disk-safe: lowercase, hyphens preserved
        if self.year:
            return f"pa_{self.kind.lower()}_{self.number}_{self.year}"
        return f"pa_{self.kind.lower()}_{self.number}"


def _parse_panama_meta(pdf_url: str, hint_kind: str) -> PanamaCircularMeta | None:
    """Extract MMC/MMN code + number (+ year for MMNs) from URL.

    Filename samples observed:
      MMC-395-IGF-CODE-March-2025.pdf                       → MMC-395
      MMC-281-OCTOBER-2025-CM.pdf                           → MMC-281
      MMN-01-2021-MAY-2023-Cancelled-13-06-2025.pdf         → MMN-01-2021
      MMN-02-2023-FUJAIRAH-REQUIREMENTS-FOR-TANKERS.pdf     → MMN-02-2023
      MMN-152022-PAYMENT-ACCOUNTS.pdf                       → MMN-15-2022 (concat)
      MMC-114-CANCELADA.pdf                                 → MMC-114
    """
    fname = pdf_url.rsplit("/", 1)[-1]
    stem = fname.rsplit(".", 1)[0]

    # Pull the leading "MMC-NNN" or "MMN-NN-YYYY" prefix.
    m = re.match(r"^(MMC|MMN)[-_]?(\d{1,4})(?:[-_]?(\d{4}))?", stem, re.IGNORECASE)
    if m:
        kind = m.group(1).upper()
        number = m.group(2).lstrip("0") or m.group(2)
        year = m.group(3) or ""
        return PanamaCircularMeta(
            kind=kind, number=number, year=year,
            pdf_url=pdf_url, filename=fname,
        )

    # No match — skip (couldn't parse).
    return None


def discover_and_download(
    raw_dir: Path, failed_dir: Path, console,
) -> tuple[int, int]:
    """For each index page (MMC + MMN), walk the listing, download each
    PDF.

    Idempotent: pre-existing PDFs > 5 KB are kept.
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    all_meta: list[PanamaCircularMeta] = []
    seen_stubs: set[str] = set()

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for kind, path in _INDEX_PAGES:
            url = _BASE + path
            try:
                console.print(f"  Discovering Panama {kind}s at {path}…")
                resp = client.get(url, headers=_HEADERS)
                resp.raise_for_status()
                pdf_urls = sorted(set(_PDF_URL_RE.findall(resp.text)))
                console.print(f"    found {len(pdf_urls)} PDF refs")
                for pdf_url in pdf_urls:
                    meta = _parse_panama_meta(pdf_url, hint_kind=kind)
                    if meta is None:
                        continue
                    if meta.filename_stub in seen_stubs:
                        continue
                    seen_stubs.add(meta.filename_stub)
                    all_meta.append(meta)
            except Exception as exc:
                logger.warning("Panama %s index: %s", kind, exc)
                console.print(f"    [yellow]ERROR: {exc}[/yellow]")
            time.sleep(_REQUEST_DELAY)

        console.print(f"  Panama: {len(all_meta)} parseable circulars/notices to fetch")

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
                    "Panama %s: download failed — %s", meta.section_number, exc,
                )
                _write_failure(meta, exc, failed_dir)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "kind":           m.kind,
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
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"Panama MMC index not found at {cache_path}. Run discovery first."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    sections: list[Section] = []
    for e in entries:
        meta = PanamaCircularMeta(
            kind=e["kind"], number=e["number"], year=e["year"],
            pdf_url=e["pdf_url"], filename=e["filename"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning(
                "Panama %s: extraction failed — %s", meta.section_number, exc,
            )
            continue
        if not text.strip() or len(text) < 400:
            logger.warning(
                "Panama %s: text too short (%d chars)",
                meta.section_number, len(text),
            )
            continue
        sections.append(Section(
            source                = SOURCE,
            title_number          = TITLE_NUMBER,
            section_number        = meta.section_number,
            section_title         = (
                f"Panama Maritime Authority — "
                f"{'Merchant Marine Circular' if meta.kind == 'MMC' else 'Marine Notice'} "
                f"{meta.number}"
                + (f"/{meta.year}" if meta.year else "")
            ),
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = meta.parent_section_number,
        ))

    logger.info("Panama: parsed %d sections from %d entries",
                len(sections), len(entries))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


def _extract_pdf_text(pdf_path: Path) -> str:
    page_texts: list[str] = []
    reader = PdfReader(str(pdf_path))
    for page in reader.pages:
        t = page.extract_text() or ""
        t = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", t)
        t = re.sub(r"[ \t]+", " ", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


def _write_failure(
    meta: PanamaCircularMeta, exc: Exception, failed_dir: Path,
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

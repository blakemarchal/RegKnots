"""
UK Maritime and Coastguard Agency notices source adapter.

Sprint D6.18 — RegKnots' first non-US national-flag corpus. Two sources
share this module:

  mca_mgn — Marine Guidance Notes (MCA's authoritative interpretation,
            Tier 2 in our authority taxonomy, parallels US NVIC).
            Suffix (M)/(F)/(M+F) marks applicability scope:
            merchant / fishing / both.

  mca_msn — Merchant Shipping Notices (Tier 1: technical detail of
            statutory instruments, often the substantive specification
            behind a UK Statutory Instrument).

Phase 1 ingests a curated set of ~20 notices most relevant to a
cross-Channel passenger ferry (Rashad's profile drove the selection).
Phase 2 will replace the curated index with a live scrape of the
MCA collection pages on GOV.UK.

Section numbering convention:
  MGN: section_number = "MGN 71 (M+F)"   (no space between number & suffix to keep parsing tractable)
  MSN: section_number = "MSN 1676 Amendment 4"
  parent_section_number = canonical form without amendment suffix

License: Open Government Licence v3.0. Commercial use, paraphrasing,
and short quotes explicitly permitted with attribution. Same posture
as our CFR ingest. The required attribution string —
  "Contains public sector information licensed under the Open
   Government Licence v3.0."
— is rendered by the chat layer when an MCA notice is cited.

Two-phase pipeline (mirrors NVIC):
  1. Download — fetch each PDF from assets.publishing.service.gov.uk
                to data/raw/mca/{kind}_{number}.pdf; idempotent.
  2. Parse    — extract text via pdfplumber, emit one Section per
                notice. Document bodies are short (5-20 pages) and
                rarely have a CFR-style subsection skeleton, so
                whole-document Sections work fine — the chunker's
                paragraph/sentence splitter handles the rest.

Curated phase-1 list lives in `_CURATED_NOTICES` below. Each entry:
  number, title, kind, suffix, pdf_url, effective_date, category.
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
from bs4 import BeautifulSoup

from ingest.models import Section

logger = logging.getLogger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

TITLE_NUMBER = 0  # not a CFR-numbered title
SOURCE_DATE  = date(2026, 4, 28)  # adapter version, not notice publication

_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-GB,en;q=0.9",
}
_REQUEST_DELAY = 1.0
_TIMEOUT       = 60.0


# ── Curated phase-1 index ────────────────────────────────────────────────────
#
# Notices selected to cover the operational surface of a cross-Channel
# passenger / ro-pax ferry (Rashad's profile). Each URL is the canonical
# PDF on assets.publishing.service.gov.uk as of 2026-04-28.
#
# When the user asks about manning hours, drills, lifesaving, ro-ro
# stability, or dangerous goods on a UK-flag vessel, these notices are
# the binding (MSN) or authoritative-interpretation (MGN) sources.

@dataclass(frozen=True)
class NoticeMeta:
    number:         str            # "71", "1676"
    title:          str
    kind:           str            # "mgn" or "msn"
    suffix:         str | None     # "M+F", "M", "F", or None
    fmt:            str            # "pdf" or "html"
    download_url:   str            # PDF asset URL or GOV.UK body URL
    effective_date: date
    category:       str            # for logging / future filtering
    amendment:      str | None = None   # "Amendment 4" if applicable

    @property
    def section_number(self) -> str:
        """Canonical citation form."""
        base = f"{self.kind.upper()} {self.number}"
        if self.suffix:
            base += f" ({self.suffix})"
        if self.amendment:
            base += f" {self.amendment}"
        return base

    @property
    def parent_section_number(self) -> str:
        """Citation without amendment suffix — the family identifier."""
        base = f"{self.kind.upper()} {self.number}"
        if self.suffix:
            base += f" ({self.suffix})"
        return base

    @property
    def filename_stub(self) -> str:
        amend = f"_amend{self.amendment.split()[-1]}" if self.amendment else ""
        return f"{self.kind}_{self.number}{amend}"

    @property
    def filename(self) -> str:
        return f"{self.filename_stub}.{self.fmt}"


_CURATED_NOTICES: list[NoticeMeta] = [
    # ── Drills / training (the question that exposed the gap) ────────────────
    NoticeMeta(
        number="71", title="Musters, Drills, On-Board Training, and Decision Support Systems",
        kind="mgn", suffix="M+F", category="drills_training",
        amendment="Amendment 1",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/mgn-71-mf-amendment-1-musters-drills-on-board-training-and-instructions-and-decision-support-systems/mgn-71-mf-amendment-1-life-saving-appliances-musters-drills-on-board-training-and-instructions-and-decision-support-systems",
        effective_date=date(2025, 4, 24),
    ),
    # ── Lifesaving appliances ────────────────────────────────────────────────
    NoticeMeta(
        number="1676", title="Merchant Shipping (Life-Saving Appliances) Regulations",
        kind="msn", suffix="M", category="lifesaving",
        amendment="Amendment 2",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/68f244be2f0fc56403a3d064/MSN.1676_A2.pdf",
        effective_date=date(2025, 10, 1),
    ),
    # ── Manning / watchkeeping ───────────────────────────────────────────────
    NoticeMeta(
        number="1868", title="UK Requirements for Safe Manning and Watchkeeping",
        kind="msn", suffix="M", category="manning_watchkeeping",
        amendment="Amendment 1",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/63a07317e90e07587364f663/Merchant_Shipping_Notice_1868__Amendment_1_.pdf",
        effective_date=date(2023, 1, 10),
    ),
    NoticeMeta(
        number="1877", title="MLC 2006 — Hours of Work and Entitlement to Leave",
        kind="msn", suffix="M", category="manning_watchkeeping",
        amendment="Amendment 2",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/msn-1877-m-maritime-labour-convention-2006-hours-of-work-and-entitlement-to-leave/msn-1877-m-amendment-2-mlc-2006-hours-of-work-and-entitlement-to-leave-application-of-the-hours-of-work-regulations-2018",
        effective_date=date(2022, 10, 4),
    ),
    NoticeMeta(
        number="315", title="Keeping a Safe Navigational Watch on Merchant Vessels",
        kind="mgn", suffix="M", category="manning_watchkeeping",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/5dc14720e5274a4aa29e3cb3/MGN_315.pdf",
        effective_date=date(2006, 2, 1),
    ),
    NoticeMeta(
        number="610", title="SOLAS Ch.V — Guidance on Safety of Navigation Regs 2020",
        kind="mgn", suffix="M+F", category="navigation",
        amendment="Amendment 1",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/mgn-610-mf-amendment-1-solas-chapter-v-guidance-on-the-merchant-shipping-safety-of-navigation-regulations-2020/mgn-610-mf-amendment-1-navigation-solas-chapter-v-guidance-on-the-merchant-shipping-safety-of-navigation-regulations-2020",
        effective_date=date(2022, 1, 1),
    ),
    # ── Passenger vessel + Ro-Ro ──────────────────────────────────────────────
    NoticeMeta(
        number="1790", title="Stability Requirements for Ro-Ro Passenger Ships",
        kind="msn", suffix="M", category="roro_stability",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/5a7f5441e5274a2e8ab4b83f/1790.pdf",
        effective_date=date(2005, 1, 1),
    ),
    NoticeMeta(
        number="1794", title="Counting and Registration of Persons on Board Passenger Ships",
        kind="msn", suffix="M", category="passenger_ops",
        amendment="Amendment 2",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/msn-1794-m-amendment-2-counting-and-registration-of-persons-on-board-passenger-ships/msn-1794-m-amendment-2-counting-and-registration-of-persons-on-board-passenger-ships",
        effective_date=date(2023, 7, 31),
    ),
    NoticeMeta(
        number="1747", title="Sea Areas — Passenger Ships on Domestic Voyages",
        kind="msn", suffix="M", category="domestic_sea_areas",
        amendment="Amendment 1",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/msn-1747-m-amendment-1-sea-areas-associated-with-the-merchant-shipping-passenger-ships-on-domestic-voyages-regulations-2000/msn-1747-m-amendment-1",
        effective_date=date(2022, 3, 17),
    ),
    NoticeMeta(
        number="635", title="Inspections of Ro-Ro Passenger Ships and HSC",
        kind="mgn", suffix="M", category="roro_inspection",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/mgn-635-m-inspections-of-ro-ro-passenger-ships-and-high-speed-passenger-craft/mgn-635-m-inspections-of-ro-ro-passenger-ships-and-high-speed-passenger-craft",
        effective_date=date(2021, 1, 1),
    ),
    NoticeMeta(
        number="1869", title="Safety Management Code for Domestic Passenger Ships",
        kind="msn", suffix="M", category="passenger_ops",
        amendment="Amendment 1",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/5e86f506e90e0706ee64a83a/MSN_1869_Amendment_1_210317_-_FINAL.pdf",
        effective_date=date(2020, 1, 3),
    ),
    # ── Fire protection ──────────────────────────────────────────────────────
    NoticeMeta(
        number="1901", title="Merchant Shipping (Fire Protection) Regulations 2023",
        kind="msn", suffix="M", category="fire_protection",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/637b3a8ae90e0728553b569e/draft-msn-1901.pdf",
        effective_date=date(2023, 1, 1),
    ),
    NoticeMeta(
        number="667", title="Guidance for MSNs 1901 and 1902 (Fire Protection)",
        kind="mgn", suffix="M", category="fire_protection",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/6489c6bdb32b9e000ca96763/MGN_667_-_Guidance_for_MSNs_1901_and_1902.pdf",
        effective_date=date(2023, 6, 14),
    ),
    # ── Dangerous goods (pairs with our IMDG ingest) ─────────────────────────
    NoticeMeta(
        number="36", title="Document of Compliance — Ships Carrying Dangerous Goods",
        kind="mgn", suffix="M+F", category="dangerous_goods",
        fmt="pdf",
        download_url="https://assets.publishing.service.gov.uk/media/5ea7f0aad3bf7f7b4e000511/MGN_36.pdf",
        effective_date=date(1997, 10, 1),
    ),
    # ── In-force registry (cross-check anchor for phase-2 discovery) ────────
    NoticeMeta(
        number="470", title="MLC 2006 — List of in-force MSNs, MGNs and MINs",
        kind="mgn", suffix="M", category="meta_registry",
        amendment="Amendment 2",
        fmt="html",
        download_url="https://www.gov.uk/government/publications/mgn-470-m-mlc-2006-list-of-merchant-shipping-notices-and-guidance-notes/mgn-470-m-amendment-2-mlc-2006-list-of-merchant-shipping-notices-marine-guidance-notes-and-marine-information-notes",
        effective_date=date(2022, 8, 15),
    ),
]


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(
    raw_dir: Path, failed_dir: Path, console
) -> tuple[int, int]:
    """Download every notice in the curated phase-1 list. Idempotent.

    Handles both formats:
      * fmt="pdf"  — write the response bytes to <stub>.pdf, must start
                     with the %PDF magic.
      * fmt="html" — write the response text to <stub>.html (the raw
                     HTML; main-content extraction happens in parse_source
                     so we can re-parse without re-downloading).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)

    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        for i, meta in enumerate(_CURATED_NOTICES, 1):
            out_path = raw_dir / meta.filename
            if out_path.exists() and out_path.stat().st_size > 512:
                logger.debug("MCA %s: already present, skipping", meta.section_number)
                success += 1
                continue
            try:
                console.print(
                    f"  Downloading {meta.section_number} [{meta.fmt}] ({i}/{len(_CURATED_NOTICES)})…"
                )
                resp = client.get(meta.download_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if meta.fmt == "pdf":
                    if not resp.content.startswith(b"%PDF"):
                        raise ValueError(
                            f"Response is not a PDF (got {resp.content[:32]!r})"
                        )
                    out_path.write_bytes(resp.content)
                elif meta.fmt == "html":
                    out_path.write_text(resp.text, encoding="utf-8")
                else:
                    raise ValueError(f"Unknown fmt: {meta.fmt!r}")
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("MCA %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < len(_CURATED_NOTICES):
                time.sleep(_REQUEST_DELAY)

    # Cache the index so parse_source can read meta without re-deriving.
    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps(
            [
                {
                    "number": m.number,
                    "title": m.title,
                    "kind": m.kind,
                    "suffix": m.suffix,
                    "fmt": m.fmt,
                    "download_url": m.download_url,
                    "effective_date": m.effective_date.isoformat(),
                    "category": m.category,
                    "amendment": m.amendment,
                }
                for m in _CURATED_NOTICES
            ],
            indent=2,
        ),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path, kind: str) -> list[Section]:
    """Parse downloaded notices for the requested `kind` (mgn or msn).

    Each notice becomes ONE Section; the chunker handles paragraph
    splitting downstream. Multi-document amendments stay separate so
    the user can see the version history if they ask about it.
    """
    if kind not in ("mgn", "msn"):
        raise ValueError(f"Unknown MCA kind: {kind!r}")
    source_code = f"mca_{kind}"

    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(
            f"MCA index cache not found at {cache_path}. "
            "Run discovery first (discover_and_download)."
        )
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)

    notices = [_meta_from_dict(e) for e in entries if e["kind"] == kind]
    sections: list[Section] = []
    for meta in notices:
        in_path = raw_dir / meta.filename
        if not in_path.exists():
            logger.warning("MCA %s: source missing at %s, skipping", meta.section_number, in_path)
            continue
        try:
            if meta.fmt == "pdf":
                text = _extract_pdf_text(in_path)
            elif meta.fmt == "html":
                text = _extract_html_text(in_path)
            else:
                raise ValueError(f"Unknown fmt: {meta.fmt!r}")
        except Exception as exc:
            logger.warning("MCA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip():
            logger.warning("MCA %s: extracted empty text, skipping", meta.section_number)
            continue
        sections.append(Section(
            source                = source_code,
            title_number          = TITLE_NUMBER,
            section_number        = meta.section_number,
            section_title         = meta.title,
            full_text             = text,
            up_to_date_as_of      = SOURCE_DATE,
            parent_section_number = meta.parent_section_number,
            published_date        = meta.effective_date,
        ))

    logger.info(
        "MCA %s: parsed %d sections from %d notice(s)",
        source_code, len(sections), len(notices),
    )
    return sections


def get_source_date(raw_dir: Path) -> date:
    """Most recent effective_date across all curated notices.

    Falls back to today if the index cache is absent.
    """
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        return date.today()
    try:
        with open(cache_path, encoding="utf-8") as fh:
            entries = json.load(fh)
        if not entries:
            return date.today()
        return max(date.fromisoformat(e["effective_date"]) for e in entries)
    except Exception:
        return date.today()


# ── Internal helpers ─────────────────────────────────────────────────────────

def _meta_from_dict(d: dict) -> NoticeMeta:
    return NoticeMeta(
        number=d["number"],
        title=d["title"],
        kind=d["kind"],
        suffix=d.get("suffix"),
        fmt=d["fmt"],
        download_url=d["download_url"],
        effective_date=date.fromisoformat(d["effective_date"]),
        category=d["category"],
        amendment=d.get("amendment"),
    )


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract page-joined text from a PDF.

    Strips bare page numbers and collapses runs of whitespace so the
    chunker's paragraph splitter sees clean input. Doesn't try to
    detect MCA-specific section structure — most notices don't have
    a deep skeleton, and the token-aware chunker handles long bodies.
    """
    page_texts: list[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            t = page.extract_text() or ""
            t = _PAGE_NUMBER_LINE.sub("", t)
            t = _MULTI_WHITESPACE.sub(" ", t)
            t = re.sub(r"\n{3,}", "\n\n", t)
            page_texts.append(t.strip())
    return "\n\n".join(p for p in page_texts if p)


def _extract_html_text(html_path: Path) -> str:
    """Extract main-content text from a GOV.UK publication body page.

    GOV.UK publication pages put substantive content inside
    <main id="content"> ... </main>; everything else (header, footer,
    cookie banner, related-content sidebar) is boilerplate that would
    pollute embeddings if left in. We pull just the main element, drop
    nav / footer / aside / script / style tags, then read text with
    paragraph-aware whitespace.
    """
    raw = html_path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(raw, "html.parser")

    # Drop chrome we never want in chunks.
    for selector in ("script", "style", "nav", "footer", "header", "aside",
                      ".gem-c-back-to-top", ".govuk-cookie-banner",
                      ".gem-c-related-navigation", ".gem-c-document-list"):
        for tag in soup.select(selector):
            tag.decompose()

    # Prefer the main element; fall back to body if missing.
    main = soup.find("main") or soup.find("body") or soup
    # `separator` keeps paragraph boundaries readable to the chunker.
    text = main.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _write_failure(meta: NoticeMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url":            meta.pdf_url,
        "error":          f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"mca_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8"
    )


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")
_MULTI_WHITESPACE = re.compile(r"[ \t]+")

"""
Bahamas Maritime Authority (BMA) — Marine Notices.

Sprint D6.22 — Bahamas is a top-10 open registry by gross tonnage.

License posture: standard copyright; treat like LISCR / IRI as fair-use
ingestion of public regulatory notices for a private RAG knowledge
base; surface attribution + source URL on cited chunks.

Direct-PDF ingest from www.bahamasmaritime.com/wp-content/uploads/<year>-<mo>/
on a deterministic per-MN URL.

Section numbering convention:
  section_number = "BMA MN<NNN>"     (e.g. "BMA MN108")
  parent_section_number = "BMA Marine Notices"
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


SOURCE       = "bma_mn"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 4, 28)

_USER_AGENT = "RegKnots/1.0 (+https://regknots.com; contact: hello@regknots.com)"
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 1.5
_TIMEOUT       = 60.0


@dataclass(frozen=True)
class MNMeta:
    code:           str    # "MN108", "MN082"
    title:          str
    pdf_url:        str
    effective_date: date
    category:       str

    @property
    def section_number(self) -> str:
        return f"BMA {self.code}"

    @property
    def parent_section_number(self) -> str:
        # Sprint D6.44 — parent now derives from category so non-MN
        # publications (Information Notices, Safety Alerts, Yacht
        # Notices, etc.) get correctly grouped in retrieval.
        labels = {
            "marine_notices":      "BMA Marine Notices",
            "information_notices": "BMA Information Notices",
            "safety_alerts":       "BMA Safety Alerts",
            "yacht_notices":       "BMA Yacht Notices",
            "technical_alerts":    "BMA Technical Alerts",
            "bulletins":           "BMA Bulletins",
        }
        return labels.get(self.category, "BMA Marine Notices")

    @property
    def filename_stub(self) -> str:
        return f"bma_{self.code.lower()}"


_BASE = "https://www.bahamasmaritime.com/wp-content/uploads"

_CURATED: list[MNMeta] = [
    MNMeta("MN108", "Hatches, Lifting Appliances and Anchor Handling Winches",
           f"{_BASE}/2025/12/MN108-Hatches-Lifting-Appliances-and-Anchor-Handling-Winches.pdf",
           date(2025, 12, 10), "cargo_gear"),
    MNMeta("MN085", "Carriage of Immersion Suits",
           f"{_BASE}/2025/11/MN085-Carriage-of-Immersion-Suits.pdf",
           date(2025, 11, 21), "lifesaving"),
    MNMeta("MN082", "Lifeboat Safety",
           f"{_BASE}/2023/10/MN082-Lifeboat-Safety.pdf",
           date(2023, 10, 30), "lifesaving"),
    MNMeta("MN079", "Firefighting Equipment",
           f"{_BASE}/2025/11/MN079-Firefighting-Equipment-1.pdf",
           date(2025, 11, 21), "fire"),
    MNMeta("MN065", "Ballast Water Management Convention",
           f"{_BASE}/2025/08/MN065-BWM.pdf",
           date(2025, 8, 26), "bwm"),
    MNMeta("MN020", "Training and Certification Requirements",
           f"{_BASE}/2025/11/MN020-Training-and-Certification-Requirements.pdf",
           date(2025, 11, 21), "stcw"),
    # The PDFs below have less-deterministic filenames; we attempt the
    # common pattern but failures are tolerable.
    MNMeta("MN018", "Safe Manning Requirements",
           f"{_BASE}/2022/05/MN018-Safe-Manning-Requirements.pdf",
           date(2022, 5, 9), "manning"),
    MNMeta("MN081", "Emergency Escape Breathing Devices (EEBDs)",
           f"{_BASE}/2023/01/MN081-EEBDs.pdf",
           date(2023, 1, 31), "fire"),
    MNMeta("MN080", "Inspection and Testing of Automatic Sprinkler Systems",
           f"{_BASE}/2023/11/MN080-Sprinklers.pdf",
           date(2023, 11, 29), "fire"),
    MNMeta("MN078", "Passenger Ship Watertight Doors",
           f"{_BASE}/2022/03/MN078-WTD.pdf",
           date(2022, 3, 14), "stability"),
    MNMeta("MN062", "MARPOL Annex VI Fuel Oil Sulphur Limit",
           f"{_BASE}/2022/05/MN062-MARPOL-Annex-VI.pdf",
           date(2022, 5, 4), "marpol"),
    MNMeta("MN060", "MARPOL Annex V",
           f"{_BASE}/2022/03/MN060-MARPOL-Annex-V.pdf",
           date(2022, 3, 14), "marpol"),
    MNMeta("MN059", "MARPOL Annex IV — Sewage",
           f"{_BASE}/2022/02/MN059-MARPOL-Annex-IV.pdf",
           date(2022, 2, 2), "marpol"),
    MNMeta("MN056", "MARPOL Oil Record Books",
           f"{_BASE}/2022/04/MN056-Oil-Record-Books.pdf",
           date(2022, 4, 5), "marpol"),
    MNMeta("MN096", "Remote Statutory Surveys, Audits and Inspections",
           f"{_BASE}/2025/11/MN096-Remote-Surveys.pdf",
           date(2025, 11, 21), "survey"),
    MNMeta("MN083", "Lifeboat / Rescue Boat Maintenance & Release Gear",
           f"{_BASE}/2021/12/MN083-Lifeboat-Maintenance.pdf",
           date(2021, 12, 6), "lifesaving"),
]


# ── Sitemap-based discovery (Sprint D6.44) ──────────────────────────────────
#
# BMA publishes a Yoast SEO sitemap at /notices-sitemap.xml that catalogs
# every notice landing page across all categories (marine-notices,
# information-notices, safety-alerts, yacht-notices, technical-alerts,
# bulletins). Each landing page embeds the PDF download URL in a
# `<a href="...wp-content/uploads/.../<file>.pdf" class="...c-btn...">Download [PDF`
# anchor. Two-stage discovery: list pages → extract PDF URLs.
#
# The hand-curated _CURATED list above is kept as a fallback for the case
# where the sitemap fetch fails — we don't want to lose existing coverage
# when BMA's site briefly hiccups.

_SITEMAP_URL = "https://www.bahamasmaritime.com/notices-sitemap.xml"
_PDF_REGEX = re.compile(
    r'href=[\'"](https?://[^\'"]*?/wp-content/uploads/[^\'"]*?\.pdf)[\'"]',
    re.IGNORECASE,
)
# Match `MN048`, `MN108-Hatches`, etc., or `BMA-Safety-Alert-21-04-...`
_CODE_FROM_URL_REGEX = re.compile(
    r'/(MN\d+|BMA[-_][^/]*|IN\d+|YN\d+|Y\d+)',
    re.IGNORECASE,
)
# Match landing-page slugs like `mn092-enhanced-monitoring-programme`,
# `bma-safety-alert-21-04-rope-access-fatal-fall`,
# `in012-bma-technical-and-safety-alerts`, etc.
_LANDING_CODE_REGEX = re.compile(
    r'/notices/(?P<category>[^/]+)/(?P<slug>[^/]+)/?$',
    re.IGNORECASE,
)

# Categories to ingest. Skipping vessels-sitemap (vessel registry data,
# not regulatory). Order matters only for log readability.
_CATEGORIES = [
    "marine-notices",       # Primary: 102 MNs
    "information-notices",  # 26 INs
    "safety-alerts",        # 25 BMA Safety Alerts
    "yacht-notices",        # 13 YNs / Yxxx
    "technical-alerts",     # 5
    "bulletins",            # 2
]


def _extract_landing_pages_from_sitemap(client: httpx.Client, console) -> list[tuple[str, str]]:
    """Returns [(category, landing_page_url)]. Empty list on any error
    so the curated list still runs. We tolerate sitemap failures."""
    try:
        resp = client.get(_SITEMAP_URL, headers=_BROWSER_HEADERS, timeout=15.0)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("BMA sitemap fetch failed (%s); skipping discovery", exc)
        console.print(f"  [yellow]BMA sitemap unreachable: {exc}[/yellow]")
        return []

    # Extract <loc>https://...</loc> URLs. Wraps regex over XML for simplicity
    # — XML parsing would be marginally cleaner but the schema is dead simple.
    locs = re.findall(r"<loc>([^<]+)</loc>", resp.text)
    out: list[tuple[str, str]] = []
    for url in locs:
        m = _LANDING_CODE_REGEX.search(url)
        if not m:
            continue
        category = m.group("category")
        if category not in _CATEGORIES:
            continue
        out.append((category, url))
    console.print(f"  [cyan]BMA sitemap:[/cyan] {len(out)} landing pages across {len(_CATEGORIES)} categories")
    return out


def _extract_pdf_url_from_landing(client: httpx.Client, landing_url: str) -> tuple[str, str] | None:
    """Fetch the landing page and pull the PDF download anchor. Returns
    (pdf_url, page_title) or None on failure."""
    try:
        resp = client.get(landing_url, headers=_BROWSER_HEADERS, timeout=15.0)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("BMA landing fetch failed for %s: %s", landing_url, exc)
        return None

    pdf_match = _PDF_REGEX.search(resp.text)
    if not pdf_match:
        return None
    pdf_url = pdf_match.group(1)

    title_match = re.search(r"<title>([^<]+)</title>", resp.text, re.IGNORECASE)
    page_title = (title_match.group(1) if title_match else "").split(" - ")[0].strip()
    return (pdf_url, page_title)


def _meta_from_landing(category: str, landing_url: str, pdf_url: str, page_title: str) -> MNMeta | None:
    """Build an MNMeta from discovery output. Code is derived from the
    PDF filename (MN108-..., BMA-Safety-Alert-21-04-..., IN012-...). Year
    is inferred from the PDF URL path /YYYY/MM/. """
    # Extract code from PDF filename
    fname = pdf_url.rsplit("/", 1)[-1]
    code_match = re.match(r"([A-Z]+[-_]?\d+(?:[-_]\d+)?)", fname, re.IGNORECASE)
    if code_match:
        code = code_match.group(1).replace("_", "-").upper()
        # Normalize MN108 / mn108 / Mn-108 etc → MN108
        code = re.sub(r"[-]+", "-", code)
        # Drop trailing -1, -v1.0 etc that some files have
        code = re.sub(r"-(v\d.*|rev\d.*|\d+)$", "", code, flags=re.IGNORECASE)
    else:
        # Fall back to landing slug if filename is malformed
        slug_match = _LANDING_CODE_REGEX.search(landing_url)
        code = slug_match.group("slug") if slug_match else fname

    # Infer year from URL path: /wp-content/uploads/YYYY/MM/...
    year_match = re.search(r"/uploads/(\d{4})/(\d{2})/", pdf_url)
    if year_match:
        try:
            effective_date = date(int(year_match.group(1)), int(year_match.group(2)), 1)
        except ValueError:
            effective_date = SOURCE_DATE
    else:
        effective_date = SOURCE_DATE

    return MNMeta(
        code=code,
        title=page_title or code,
        pdf_url=pdf_url,
        effective_date=effective_date,
        category=category.replace("-", "_"),
    )


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        # Sprint D6.44 — combine curated with sitemap-discovered. Curated
        # serves as a guaranteed-coverage fallback if discovery fails.
        # De-dupe by code so we don't double-count when both find the same
        # notice.
        all_metas: list[MNMeta] = list(_CURATED)
        seen_codes = {m.code.upper() for m in all_metas}

        landing_pages = _extract_landing_pages_from_sitemap(client, console)
        for i, (category, landing_url) in enumerate(landing_pages, 1):
            time.sleep(0.5)  # be polite to the BMA WP host
            extracted = _extract_pdf_url_from_landing(client, landing_url)
            if not extracted:
                continue
            pdf_url, page_title = extracted
            meta = _meta_from_landing(category, landing_url, pdf_url, page_title)
            if meta is None or meta.code.upper() in seen_codes:
                continue
            seen_codes.add(meta.code.upper())
            all_metas.append(meta)
        console.print(f"  [cyan]BMA discovery:[/cyan] {len(all_metas)} total notices ({len(_CURATED)} curated + {len(all_metas) - len(_CURATED)} discovered)")

        # Phase 2 — download all PDFs
        total = len(all_metas)
        for i, meta in enumerate(all_metas, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                console.print(f"  Downloading {meta.section_number} ({i}/{total})…")
                resp = client.get(meta.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
                out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("BMA %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            if i < total:
                time.sleep(_REQUEST_DELAY)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "effective_date": m.effective_date.isoformat(), "category": m.category}
            for m in all_metas
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"BMA index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = MNMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            effective_date=date.fromisoformat(e["effective_date"]),
            category=e["category"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("BMA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("BMA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("BMA %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("BMA: parsed %d sections from %d notice(s)", len(sections), len(entries))
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


def _write_failure(meta: MNMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"bma_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")


_PAGE_NUMBER_LINE = re.compile(r"(?m)^\s*\d{1,4}\s*$")

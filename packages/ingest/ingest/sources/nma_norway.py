"""
Norwegian Maritime Authority (Sjøfartsdirektoratet / NMA) circulars.

Sprint D6.46 — full-circular expansion via NMA's public sitemap
(replaces the original D6.23 30-entry hand-curated list).

License: Norwegian Crown copyright. NMA explicitly publishes circulars
for compliance use; fair-use ingestion of public regulatory content
for a private RAG knowledge base.

Discovery flow:
  1. Fetch https://www.sdir.no/sitemap.xml (3500 URLs, server-rendered).
  2. Filter to landing pages under /rundskriv/ (NMA's circular series —
     mixed EN + NO content). Sitemap exposes ~600 active circulars.
  3. For each landing page, follow the redirect to the canonical
     /regelverk/rundskriv/<slug>/ form (Cloudflare 302 reroute).
  4. Extract the contentassets PDF URL via regex on the rendered HTML.
  5. Download + parse via pdfplumber.

Section numbering convention:
  section_number = "NMA RSR 8-2014" / "NMA RSV 9-2020" / "NMA SM 6-2009"
                   (preserves the NMA series prefix: RSR = regulation,
                    RSV = circular guidance, SM = safety message)
                   Falls back to slugified URL if series not parseable.
  parent_section_number = "NMA Norway"

Language: Most circulars are in Norwegian (lang="no") with selected
EN translations. We tag each chunk with the language detected from
filename heuristics (eng-* prefix → en, otherwise no).
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


SOURCE       = "nma_rsv"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 1)


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,no;q=0.7",
}
_REQUEST_DELAY = 0.6
_TIMEOUT       = 30.0
_MAX_PDF_BYTES = 15 * 1024 * 1024


_SITEMAP_URL  = "https://www.sdir.no/sitemap.xml"
_RUNDSKRIV_RE = re.compile(r"https://www\.sdir\.no/rundskriv/([^/]+)/?$", re.IGNORECASE)
_PDF_HREF_RE  = re.compile(
    r'href=["\']?(/contentassets/[^"\']+?\.pdf)["\']?', re.IGNORECASE
)
_TITLE_RE     = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)
# The filename often encodes the series:
#   eng-rsr-17-2021.pdf, eng-rsv-09-2020.pdf, rsr-3-2021.pdf,
#   nis-5-2003.pdf, sm-6-2009.pdf
_SERIES_RE = re.compile(
    r"(?:eng-)?(?P<series>rsr|rsv|sm|nis|ic)[-_](?P<num>\d+)[-_](?P<year>\d{4})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CircularMeta:
    code:           str    # "RSR 8-2014", "RSV 9-2020", "SM 6-2009"
    title:          str
    pdf_url:        str
    landing_url:    str
    effective_date: date
    category:       str
    language:       str    # "en" or "no" — detected from filename

    @property
    def section_number(self) -> str:
        return f"NMA {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "NMA Norway"

    @property
    def filename_stub(self) -> str:
        return "nma_" + re.sub(r"[^a-z0-9]+", "_",
                               self.code.lower()).strip("_")


# ── Discovery ────────────────────────────────────────────────────────────────


def _fetch_sitemap_landings(client: httpx.Client, console) -> list[str]:
    """Pull /rundskriv/<slug>/ URLs from the public sitemap."""
    try:
        resp = client.get(_SITEMAP_URL, headers=_BROWSER_HEADERS, timeout=_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("NMA sitemap fetch failed: %s", exc)
        console.print(f"  [yellow]NMA sitemap error: {exc}[/yellow]")
        return []
    locs = re.findall(r"<loc>(.*?)</loc>", resp.text)
    landings = [u for u in locs if _RUNDSKRIV_RE.match(u)]
    console.print(
        f"  [cyan]NMA sitemap:[/cyan] {len(locs)} URLs total, "
        f"{len(landings)} circulars"
    )
    return landings


def _meta_from_landing(client: httpx.Client, landing_url: str) -> CircularMeta | None:
    """Resolve landing page → PDF URL + metadata. Returns None on failure."""
    try:
        resp = client.get(landing_url, headers=_BROWSER_HEADERS,
                          timeout=20.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        logger.debug("NMA landing fetch failed for %s: %s", landing_url, exc)
        return None

    html = resp.text
    pdf_match = _PDF_HREF_RE.search(html)
    if not pdf_match:
        return None
    pdf_path = pdf_match.group(1)
    pdf_url = "https://www.sdir.no" + pdf_path

    # Title from <title> tag, stripped of " | Sjøfartsdirektoratet" suffix.
    title_match = _TITLE_RE.search(html)
    title = (title_match.group(1).strip() if title_match else
             re.sub(r"-", " ", _RUNDSKRIV_RE.match(landing_url).group(1).strip()))
    title = re.sub(
        r"\s*[\|–]\s*Sjøfartsdirektoratet.*$", "", title
    ).strip()
    title = title[:200]

    # Derive code from PDF filename. Falls back to slug if no match.
    pdf_filename = pdf_path.rsplit("/", 1)[-1]
    series_match = _SERIES_RE.search(pdf_filename)
    if series_match:
        series = series_match.group("series").upper()
        num = series_match.group("num")
        year = series_match.group("year")
        code = f"{series} {num}-{year}"
        try:
            effective = date(int(year), 1, 1)
        except ValueError:
            effective = SOURCE_DATE
    else:
        # Fall back to slug-derived code so we still index the doc.
        slug = _RUNDSKRIV_RE.match(landing_url).group(1)
        code = "MISC " + re.sub(r"[^a-z0-9]+", "-", slug.lower())[:60]
        effective = SOURCE_DATE

    # Language: filename prefix "eng-*" → English; everything else → Norwegian.
    language = "en" if pdf_filename.lower().startswith("eng-") else "no"

    return CircularMeta(
        code=code,
        title=title,
        pdf_url=pdf_url,
        landing_url=landing_url,
        effective_date=effective,
        category="rundskriv",
        language=language,
    )


# ── Public API ───────────────────────────────────────────────────────────────


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0

    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        landings = _fetch_sitemap_landings(client, console)
        metas: list[CircularMeta] = []
        seen_codes: set[str] = set()
        for i, landing_url in enumerate(landings, 1):
            time.sleep(_REQUEST_DELAY)
            meta = _meta_from_landing(client, landing_url)
            if meta is None:
                continue
            if meta.section_number in seen_codes:
                continue
            seen_codes.add(meta.section_number)
            metas.append(meta)
            if i % 50 == 0:
                console.print(
                    f"    discovery: {i}/{len(landings)} "
                    f"({len(metas)} hits)…"
                )

        console.print(f"  [cyan]NMA confirmed PDFs:[/cyan] {len(metas)}")

        for i, meta in enumerate(metas, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                if i == 1 or i == len(metas) or i % 50 == 0:
                    console.print(f"  Downloading {meta.section_number} ({i}/{len(metas)})…")
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
                logger.warning("NMA %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            time.sleep(0.3)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "landing_url": m.landing_url,
             "effective_date": m.effective_date.isoformat(),
             "category": m.category, "language": m.language}
            for m in metas
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"NMA index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = CircularMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            landing_url=e.get("landing_url", ""),
            effective_date=date.fromisoformat(e["effective_date"]),
            category=e["category"],
            language=e.get("language", "no"),
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("NMA %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("NMA %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("NMA %s: text too short (%d), skipping", meta.section_number, len(text))
            continue
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=meta.section_number,
            section_title=meta.title,
            full_text=text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=meta.parent_section_number,
            published_date=meta.effective_date,
            language=meta.language,
        ))
    logger.info("NMA: parsed %d sections from %d circular(s)", len(sections), len(entries))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal ─────────────────────────────────────────────────────────────────


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


def _write_failure(meta: CircularMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

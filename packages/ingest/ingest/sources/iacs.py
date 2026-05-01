"""
IACS Unified Requirements (URs) source adapter.

Sprint D6.45 — full-series expansion via IACS public Elasticsearch
(appbase.io) discovery, replacing the original D6.23 hand-curated 28-UR
mirror list.

License: IACS publishes URs publicly with reproduction permitted under
IACS PR 38 with attribution.

Authority tier: Tier 4 (domain technical reference standard, like ERG).

Discovery flow (parallels iacs_pr.py):
  1. Query IACS appbase Elasticsearch (anonymous credentials extracted
     from their public Nuxt frontend) for all publications.
  2. Keep entries whose post_title starts with "UR " (covering UR-A,
     UR-E, UR-F, UR-M, UR-S, UR-W, UR-Z series — ~307 in current index).
  3. For each UR, fetch the iacs.org.uk landing page.
  4. Extract the Clean (CLN) PDF URL from the Nuxt SSR state.
  5. Download from S3 + parse via pdfplumber.

Section numbering convention:
  section_number = "IACS UR S11"   (or "IACS UR Z10.1" / "IACS UR M53")
  parent_section_number = "IACS Unified Requirements"
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


SOURCE       = "iacs_ur"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 1)


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_REQUEST_DELAY = 0.6
_TIMEOUT       = 30.0
# Skip oversized PDFs (>15MB are usually image-only / scanned engineering
# tables that yield little useful text and stress pdfplumber memory).
_MAX_PDF_BYTES = 15 * 1024 * 1024


# IACS appbase.io public search index.
_APPBASE_HOST = "https://iacs-app-gcp-zkxvyue-arc.searchbase.io"
_APPBASE_INDEX = "iacs-search"
_APPBASE_USER = "8050ba66c69d"
_APPBASE_PASS = "31c2d972-6a49-4e3f-b2ce-6f2ed089cf32"

# URs live under /resolutions/ur-<letter>/. Title-prefix is "UR" followed
# by space or hyphen. Allow both as title formatting varies across the
# UR-A / UR-E / UR-F / UR-M / UR-S / UR-W / UR-Z series.
_UR_PATH_REGEX  = re.compile(r"^/resolutions/ur-[a-z]+/", re.IGNORECASE)
_UR_TITLE_REGEX = re.compile(r"^UR[\s-]", re.IGNORECASE)

# Match PDF URLs in Nuxt SSR state (handles both / and / encodings).
_S3_PDF_REGEX = re.compile(
    r"iacs\.s3\.af-south-1\.amazonaws\.com"
    r"(?:\\?u002[Ff]|/)"
    r"wp-content"
    r"(?:\\?u002[Ff]|/)"
    r"uploads"
    r"(?:\\?u002[Ff]|/)"
    r"[^\"'\s]+?\.pdf",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class URMeta:
    code:           str    # "S11", "Z10.1", "M53", "E26"
    title:          str
    pdf_url:        str
    series:         str    # "ur-s", "ur-z", "ur-m", "ur-e"

    @property
    def section_number(self) -> str:
        return f"IACS UR {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "IACS Unified Requirements"

    @property
    def filename_stub(self) -> str:
        return "iacs_ur_" + re.sub(r"[^a-z0-9]+", "_",
                                   self.code.lower()).strip("_")


# ── Discovery ────────────────────────────────────────────────────────────────


def _query_appbase(client: httpx.Client, console) -> list[dict]:
    """Page through the appbase index until exhausted."""
    all_hits: list[dict] = []
    page_size = 100
    offset = 0
    auth = httpx.BasicAuth(_APPBASE_USER, _APPBASE_PASS)
    while True:
        body = {
            "size": page_size,
            "from": offset,
            "_source": ["post_title", "post_url", "publication_description"],
            "query": {"match_all": {}},
        }
        try:
            resp = client.post(
                f"{_APPBASE_HOST}/{_APPBASE_INDEX}/_search",
                json=body, auth=auth, timeout=20.0,
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
        except Exception as exc:
            logger.warning("IACS appbase fetch failed at offset %d: %s", offset, exc)
            console.print(f"  [yellow]IACS appbase error: {exc}[/yellow]")
            break
        data = resp.json()
        hits = data.get("hits", {}).get("hits", [])
        if not hits:
            break
        all_hits.extend(hits)
        if len(all_hits) >= 5000:  # safety cap
            break
        if len(hits) < page_size:
            break
        offset += page_size
        time.sleep(0.2)
    console.print(f"  [cyan]IACS appbase:[/cyan] {len(all_hits)} total publications fetched")
    return all_hits


def _filter_to_urs(hits: list[dict]) -> list[dict]:
    """Keep publications matching both UR URL prefix and UR title prefix.
    Skip 'Deleted' tombstones — IACS keeps retired URs in the index with
    landing pages that just say the requirement was withdrawn."""
    out = []
    for h in hits:
        src = h.get("_source", {})
        url = src.get("post_url", "")
        title = (src.get("post_title", "") or "").strip()
        if not (_UR_PATH_REGEX.match(url) and _UR_TITLE_REGEX.match(title)):
            continue
        # Tombstones: title or URL contains "Deleted" / "-deleted-".
        if re.search(r"\bdeleted\b", title, re.IGNORECASE):
            continue
        if re.search(r"-deleted(-|/|$)", url, re.IGNORECASE):
            continue
        out.append(h)
    return out


def _extract_pdf_url(landing_html: str) -> str | None:
    """Find the first IACS S3 PDF URL in the Nuxt SSR state. Prefers
    'CLN' (clean) over 'UL' (uplift) variants when both are present."""
    matches = _S3_PDF_REGEX.findall(landing_html)
    if not matches:
        return None
    decoded = [m.replace("\\u002F", "/").replace("\\\\u002F", "/") for m in matches]
    decoded = ["https://" + d for d in decoded]
    for url in decoded:
        if "-CLN" in url or "_CLN" in url or "-cln" in url.lower():
            return url
    return decoded[0]


def _code_from_title(title: str) -> str:
    """Extract e.g. 'S11' from 'UR S11 — Longitudinal Strength Standard'.
    Falls back to the whole title-second-word if no clean match."""
    # "UR S11 (Rev.7 …)" or "UR Z10.1 …" or "UR-S11" or "UR M53" etc.
    m = re.match(r"^UR[\s-]+([A-Z][A-Z0-9.]*)", title.upper())
    if m:
        return m.group(1)
    parts = title.split()
    return parts[1] if len(parts) > 1 else title


def _meta_from_hit(client: httpx.Client, hit: dict) -> URMeta | None:
    """Fetch landing page, extract PDF URL, build URMeta."""
    src = hit.get("_source", {})
    post_url = src.get("post_url", "")
    title = src.get("post_title", "").strip()
    description = src.get("publication_description", "") or ""

    if not post_url or not title:
        return None

    series_match = _UR_PATH_REGEX.match(post_url)
    if not series_match:
        return None
    series = series_match.group(0).strip("/").split("/")[-1]  # e.g. "ur-s"

    landing_url = "https://iacs.org.uk" + post_url
    try:
        resp = client.get(landing_url, headers=_BROWSER_HEADERS, timeout=20.0)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("IACS UR landing fetch failed for %s: %s", landing_url, exc)
        return None

    pdf_url = _extract_pdf_url(resp.text)
    if not pdf_url:
        return None

    code = _code_from_title(title)
    return URMeta(
        code=code,
        title=description.strip().rstrip(".") or title,
        pdf_url=pdf_url,
        series=series,
    )


# ── Public ingest API ────────────────────────────────────────────────────────


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        all_hits = _query_appbase(client, console)
        ur_hits = _filter_to_urs(all_hits)
        console.print(f"  [cyan]IACS UR filter:[/cyan] {len(ur_hits)} URs identified")

        metas: list[URMeta] = []
        seen_codes: set[str] = set()
        for i, hit in enumerate(ur_hits, 1):
            time.sleep(_REQUEST_DELAY)
            meta = _meta_from_hit(client, hit)
            if meta is None:
                continue
            if meta.section_number in seen_codes:
                continue
            seen_codes.add(meta.section_number)
            metas.append(meta)
            if i % 25 == 0:
                console.print(f"    discovery: {i}/{len(ur_hits)}…")
        console.print(f"  [cyan]IACS UR landing pages:[/cyan] {len(metas)} PDF URLs extracted")

        total = len(metas)
        for i, meta in enumerate(metas, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                if i == 1 or i == total or i % 25 == 0:
                    console.print(f"  Downloading {meta.section_number} ({i}/{total})…")
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
                logger.warning("IACS UR %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            time.sleep(0.3)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "series": m.series}
            for m in metas
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"IACS UR index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = URMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            series=e["series"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("IACS UR %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("IACS UR %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("IACS UR %s: text too short (%d), skipping", meta.section_number, len(text))
            continue
        sections.append(Section(
            source=SOURCE, title_number=TITLE_NUMBER,
            section_number=meta.section_number,
            section_title=meta.title,
            full_text=text,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=meta.parent_section_number,
            published_date=SOURCE_DATE,
        ))
    logger.info("IACS UR: parsed %d sections from %d UR(s)", len(sections), len(entries))
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


def _write_failure(meta: URMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"iacs_ur_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

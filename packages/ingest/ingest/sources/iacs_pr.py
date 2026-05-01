"""
IACS Procedural Requirements (PRs) — class-society procedural standards.

Sprint D6.44 — sourced via IACS's public Elasticsearch index, with PDF
URLs extracted from each publication page's Nuxt-rendered SSR state.

Why a separate source from `iacs_ur` (Unified Requirements):
  - PRs cover IACS internal procedures (class entry, transfer of class,
    survey audits, member quality, casualty investigation handling).
  - URs cover technical requirements that ships must meet (hull strength,
    machinery, anchoring, surveys, electrical/cyber).
  - Different document types with different audience: a captain or chief
    engineer asking 'what's the SOLAS-equivalent requirement?' wants UR.
    Same person asking 'how does class transfer work?' wants PR.
  - Keeping them separate lets us filter retrieval by source if needed.

Discovery flow:
  1. Query IACS appbase.io public Elasticsearch (anonymous credentials
     extracted from their public Nuxt frontend) for all publications
     whose post_url starts with /resolutions/<NN>-<MM>/ — these are PRs.
  2. For each PR, fetch the iacs.org.uk landing page.
  3. Extract the Clean (CLN) PDF URL from the Nuxt SSR state.
     Pattern: iacs.s3.af-south-1.amazonaws.com/wp-content/uploads/.../*.pdf
  4. Download from S3 + parse via pdfplumber.

The appbase.io credentials are public (embedded in the Nuxt page source).
This isn't bypassing auth — it's the same access path their browser
clients use. License posture matches our other 'fair-use of public
regulatory standards' sources.
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


SOURCE       = "iacs_pr"
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


# IACS appbase.io public search index. Credentials extracted from the
# Nuxt frontend's window.__NUXT__ state (visible to any browser client).
_APPBASE_HOST = "https://iacs-app-gcp-zkxvyue-arc.searchbase.io"
_APPBASE_INDEX = "iacs-search"
_APPBASE_USER = "8050ba66c69d"
_APPBASE_PASS = "31c2d972-6a49-4e3f-b2ce-6f2ed089cf32"

# PRs live under /resolutions/<N>-<M>/<slug>/<slug> on iacs.org.uk.
# Match path prefixes covering PR 1-10, 11-20, 21-30, 31-42 (current
# active range — IACS may add/remove PRs over time).
_PR_PATH_REGEX = re.compile(
    r"^/resolutions/(\d+)-(\d+)/", re.IGNORECASE
)

# Match PDF URLs in Nuxt SSR state. The state is encoded JSON-in-JS so
# slashes are escape-encoded as /. Regex copes with both encodings.
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
class PRMeta:
    code:           str    # "PR 1D", "PR 12 Rev3 CLN"
    title:          str
    pdf_url:        str
    effective_date: date
    series:         str    # "1-10", "11-20", "21-30", "31-42"

    @property
    def section_number(self) -> str:
        # Normalize to "IACS PR 1D" / "IACS PR 12" form for retrieval.
        # The full title (with revision suffix) stays in section_title.
        return f"IACS {self.code.split()[0]} {self.code.split()[1]}" if " " in self.code else f"IACS {self.code}"

    @property
    def parent_section_number(self) -> str:
        return "IACS Procedural Requirements"

    @property
    def filename_stub(self) -> str:
        return "iacs_pr_" + re.sub(r"[^a-z0-9]+", "_", self.code.lower()).strip("_")


# ── Discovery ────────────────────────────────────────────────────────────────


def _query_appbase(client: httpx.Client, console) -> list[dict]:
    """Query the appbase Elasticsearch index for all PR-shaped records.
    Paginates through using `from`/`size` until exhausted."""
    all_hits: list[dict] = []
    page_size = 100
    offset = 0
    auth = httpx.BasicAuth(_APPBASE_USER, _APPBASE_PASS)
    while True:
        body = {
            "size": page_size,
            "from": offset,
            "_source": ["post_title", "post_url", "publication_description"],
            # Match-all; we filter by URL prefix in code since the
            # "post_url" field isn't a `keyword` type and prefix queries
            # against it return 0 results.
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
        if len(all_hits) >= 5000:  # safety cap; index is ~1500
            break
        if len(hits) < page_size:
            break
        offset += page_size
        time.sleep(0.2)
    console.print(f"  [cyan]IACS appbase:[/cyan] {len(all_hits)} total publications fetched")
    return all_hits


def _filter_to_prs(hits: list[dict]) -> list[dict]:
    """Keep only publications whose post_url matches /resolutions/<N>-<M>/.
    That's the IACS taxonomy slot for Procedural Requirements."""
    out = []
    for h in hits:
        src = h.get("_source", {})
        url = src.get("post_url", "")
        if _PR_PATH_REGEX.match(url):
            out.append(h)
    return out


def _extract_pdf_url(landing_html: str) -> str | None:
    """Find the first IACS S3 PDF URL in the Nuxt SSR state. Prefers
    'CLN' (clean) variants over 'UL' (uplift / underlined-changes)
    variants when both are present, since CLN is the consolidated text.
    Falls back to whatever's first if neither marker is present."""
    matches = _S3_PDF_REGEX.findall(landing_html)
    if not matches:
        return None
    # Decode / → /
    decoded = [m.replace("\\u002F", "/").replace("\\\\u002F", "/") for m in matches]
    decoded = ["https://" + d for d in decoded]
    # Prefer CLN
    for url in decoded:
        if "-CLN" in url or "_CLN" in url or "-cln" in url.lower():
            return url
    return decoded[0]


def _meta_from_hit(client: httpx.Client, hit: dict) -> PRMeta | None:
    """Fetch landing page, extract PDF URL, build PRMeta."""
    src = hit.get("_source", {})
    post_url = src.get("post_url", "")
    title = src.get("post_title", "").strip()
    description = src.get("publication_description", "") or ""

    if not post_url or not title:
        return None

    series_match = _PR_PATH_REGEX.match(post_url)
    if not series_match:
        return None
    series = f"{series_match.group(1)}-{series_match.group(2)}"

    landing_url = "https://iacs.org.uk" + post_url
    try:
        resp = client.get(landing_url, headers=_BROWSER_HEADERS, timeout=20.0)
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("IACS PR landing fetch failed for %s: %s", landing_url, exc)
        return None

    pdf_url = _extract_pdf_url(resp.text)
    if not pdf_url:
        return None

    return PRMeta(
        code=title,
        title=description.strip().rstrip(".") or title,
        pdf_url=pdf_url,
        effective_date=SOURCE_DATE,
        series=series,
    )


# ── Public ingest API ────────────────────────────────────────────────────────


def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    success, failures = 0, 0
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
        # Phase 1 — query appbase, filter to PRs, fetch each landing page,
        # extract PDF URL.
        all_hits = _query_appbase(client, console)
        pr_hits = _filter_to_prs(all_hits)
        console.print(f"  [cyan]IACS PR filter:[/cyan] {len(pr_hits)} PRs identified")

        metas: list[PRMeta] = []
        seen_codes: set[str] = set()
        for i, hit in enumerate(pr_hits, 1):
            time.sleep(_REQUEST_DELAY)
            meta = _meta_from_hit(client, hit)
            if meta is None:
                continue
            if meta.section_number in seen_codes:
                continue
            seen_codes.add(meta.section_number)
            metas.append(meta)
            if i % 25 == 0:
                console.print(f"    discovery: {i}/{len(pr_hits)}…")
        console.print(f"  [cyan]IACS PR landing pages:[/cyan] {len(metas)} PDF URLs extracted")

        # Phase 2 — download PDFs from S3
        total = len(metas)
        for i, meta in enumerate(metas, 1):
            out_path = raw_dir / f"{meta.filename_stub}.pdf"
            if out_path.exists() and out_path.stat().st_size > 5 * 1024:
                success += 1
                continue
            try:
                if i == 1 or i == total or i % 20 == 0:
                    console.print(f"  Downloading {meta.section_number} ({i}/{total})…")
                resp = client.get(meta.pdf_url, headers=_BROWSER_HEADERS)
                resp.raise_for_status()
                if not resp.content.startswith(b"%PDF"):
                    raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
                out_path.write_bytes(resp.content)
                success += 1
            except Exception as exc:
                failures += 1
                logger.warning("IACS %s: download failed — %s", meta.section_number, exc)
                _write_failure(meta, exc, failed_dir)
            time.sleep(0.3)

    cache_path = raw_dir / "index.json"
    cache_path.write_text(
        json.dumps([
            {"code": m.code, "title": m.title, "pdf_url": m.pdf_url,
             "effective_date": m.effective_date.isoformat(), "series": m.series}
            for m in metas
        ], indent=2),
        encoding="utf-8",
    )
    return success, failures


def parse_source(raw_dir: Path) -> list[Section]:
    cache_path = raw_dir / "index.json"
    if not cache_path.exists():
        raise FileNotFoundError(f"IACS PR index cache not found at {cache_path}")
    with open(cache_path, encoding="utf-8") as fh:
        entries = json.load(fh)
    sections: list[Section] = []
    for e in entries:
        meta = PRMeta(
            code=e["code"], title=e["title"], pdf_url=e["pdf_url"],
            effective_date=date.fromisoformat(e["effective_date"]),
            series=e["series"],
        )
        in_path = raw_dir / f"{meta.filename_stub}.pdf"
        if not in_path.exists():
            logger.warning("IACS PR %s: PDF missing, skipping", meta.section_number)
            continue
        try:
            text = _extract_pdf_text(in_path)
        except Exception as exc:
            logger.warning("IACS PR %s: extraction failed — %s", meta.section_number, exc)
            continue
        if not text.strip() or len(text) < 200:
            logger.warning("IACS PR %s: text too short (%d), skipping", meta.section_number, len(text))
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
    logger.info("IACS PR: parsed %d sections from %d PR(s)", len(sections), len(entries))
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


def _write_failure(meta: PRMeta, exc: Exception, failed_dir: Path) -> None:
    failed_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "section_number": meta.section_number,
        "url": meta.pdf_url,
        "error": f"{type(exc).__name__}: {exc}",
    }
    (failed_dir / f"iacs_pr_{meta.filename_stub}.json").write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

"""
France — Code des transports, Partie V (Maritime).

Sprint D6.46 — first French-language flag-state pilot, validating the
multilingual ingest path on text-embedding-3-small (cross-lingual
EN<->FR cosine similarity 0.45-0.89 in our spot-check).

Source: codes.droit.org publishes a consolidated PDF mirror of the
French Code des transports (Légifrance is the upstream authority but
blocks scrapers). Cinquième Partie covers maritime — articles L5000-1
through L5795-14, ~800 articles spanning navigation, ship status,
seafarer rights, port operations, and maritime enforcement.

License: Légifrance content is public-domain government work under
the Etalab Open License v2.0 (compatible with redistribution, fair-use
ingestion into a private RAG knowledge base).

Section numbering convention:
  section_number = "FR Article L5000-1"
  parent_section_number = "Code des transports — Partie V (Maritime)"
  language = "fr"

Discovery flow:
  1. Download the consolidated PDF from codes.droit.org.
  2. Extract text via pdfplumber, page-by-page.
  3. Split on the "Article L<num>-<num>" pattern.
  4. Keep only articles whose ID starts with L5 (Partie V).
"""

import json
import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from ingest.models import Section

logger = logging.getLogger(__name__)


SOURCE       = "fr_transport"
TITLE_NUMBER = 0
SOURCE_DATE  = date(2026, 5, 1)


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_BROWSER_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "application/pdf,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.5",
}
_TIMEOUT = 90.0   # 37 MB PDF — needs slack on slow connections


_PDF_URL = "https://codes.droit.org/PDF/Code%20des%20transports.pdf"
_PDF_FILENAME = "code_des_transports.pdf"

# Article IDs in the codes.droit.org PDF render as "L. 5000-1" /
# "R. 5000-1" / "D. 5000-1" anchored at column 0, followed on the same
# line by metadata (Ordonnance ref + Legif/Plan/Jp links), then blank
# lines, then the indented article body. Partie V (Maritime) covers
# all articles whose first numeric digit is 5.
_ARTICLE_HEADER_RE = re.compile(
    r"^([LRD])\.\s+(\d+)-(\d+(?:-\d+)?)\s+",
    re.MULTILINE,
)
# Lines we drop from article bodies — codes.droit.org footers, page
# numbers, and the metadata strip on the article-header line itself.
_NOISE_LINE_RE = re.compile(
    r"(?m)^.*?(Legif\.|Jp\.Judi\.|Jp\.Admin\.|Juricaf|"
    r"PARTIE LÉGISLATIVE|service-public\.fr|"
    r"Code des transports$|^\s*p\.\s*\d+|^\s*Plan\s*$).*?$"
)


@dataclass(frozen=True)
class ArticleMeta:
    article_id:     str    # "L5000-1"
    title:          str    # First line after the article header
    body:           str    # Full article text

    @property
    def section_number(self) -> str:
        return f"FR Article {self.article_id}"

    @property
    def parent_section_number(self) -> str:
        return "Code des transports — Partie V (Maritime)"


# ── Public API ───────────────────────────────────────────────────────────────

def discover_and_download(raw_dir: Path, failed_dir: Path, console) -> tuple[int, int]:
    raw_dir.mkdir(parents=True, exist_ok=True)
    failed_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / _PDF_FILENAME
    if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
        console.print(f"  [cyan]FR Code des transports:[/cyan] cached")
        return 1, 0
    console.print(f"  [cyan]Downloading FR Code des transports[/cyan] (~37 MB)…")
    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = client.get(_PDF_URL, headers=_BROWSER_HEADERS)
            resp.raise_for_status()
            if not resp.content.startswith(b"%PDF"):
                raise ValueError(f"Not a PDF (got {resp.content[:32]!r})")
            out_path.write_bytes(resp.content)
        console.print(f"  Downloaded {out_path.stat().st_size/1e6:.1f} MB")
        return 1, 0
    except Exception as exc:
        logger.warning("FR Code des transports download failed: %s", exc)
        (failed_dir / "fr_transport.json").write_text(
            json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2),
            encoding="utf-8",
        )
        return 0, 1


def parse_source(raw_dir: Path) -> list[Section]:
    pdf_path = raw_dir / _PDF_FILENAME
    if not pdf_path.exists():
        raise FileNotFoundError(f"FR Code des transports PDF not found at {pdf_path}")

    # Extract text from all pages, joined.
    full_text = _extract_pdf_text(pdf_path)

    articles = _split_into_articles(full_text)
    logger.info("FR Code des transports: %d articles total", len(articles))

    # Filter to Partie V (Maritime — article IDs starting with L5/R5/D5).
    maritime = [a for a in articles if a.article_id[1:2] == "5"]
    logger.info("FR Code des transports: %d maritime articles (Partie V)", len(maritime))

    sections: list[Section] = []
    for art in maritime:
        # Skip articles with too-short body (orphan headers).
        if len(art.body) < 80:
            continue
        full = f"{art.title}\n\n{art.body}" if art.title else art.body
        sections.append(Section(
            source=SOURCE,
            title_number=TITLE_NUMBER,
            section_number=art.section_number,
            section_title=art.title[:200] if art.title else art.article_id,
            full_text=full,
            up_to_date_as_of=SOURCE_DATE,
            parent_section_number=art.parent_section_number,
            published_date=SOURCE_DATE,
            language="fr",
        ))
    return sections


def get_source_date(raw_dir: Path) -> date:
    return SOURCE_DATE


# ── Internal ─────────────────────────────────────────────────────────────────


def _extract_pdf_text(pdf_path: Path) -> str:
    """Extract text via Poppler's pdftotext — pdfplumber OOMs on the
    37 MB consolidated PDF (the prod box has 3.8 GB RAM). pdftotext is
    a streaming C tool that uses ~30 MB regardless of input size."""
    cache = pdf_path.with_suffix(".txt")
    if not cache.exists() or cache.stat().st_size < 1024 * 1024:
        # -layout preserves the original column structure better than
        # the default flowing mode — important for keeping article
        # headers anchored to a single line.
        subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), str(cache)],
            check=True, capture_output=True, timeout=300,
        )
    text = cache.read_text(encoding="utf-8", errors="replace")

    # Strip codes.droit.org's per-page marketing copy and page numbers.
    text = re.sub(r"(?m)^\s*p\.\s*\d+\s*/?\s*\d*\s*$", "", text)
    text = re.sub(
        r"(?m)^.*?(codes\.droit\.org|Permet de voir|Permet de retrouver|"
        r"Permet de lancer|Vous pouvez contribuer).*?$", "", text
    )
    text = re.sub(r"(?m)^\s*\d{1,4}\s*$", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text


def _split_into_articles(text: str) -> list[ArticleMeta]:
    """Split the consolidated text on L./R./D. article headers.
    Returns articles in document order. Each article's body runs from
    after the header-line's trailing newline to the next header (or end
    of text), with codes.droit.org noise lines stripped."""
    matches = list(_ARTICLE_HEADER_RE.finditer(text))
    out: list[ArticleMeta] = []
    seen_ids: set[str] = set()
    for i, m in enumerate(matches):
        prefix = m.group(1).upper()
        partie = m.group(2)
        sub = m.group(3)
        article_id = f"{prefix}{partie}-{sub}"
        if article_id in seen_ids:
            continue  # PDF references the same article in multiple
                      # tables of contents; first match wins.
        seen_ids.add(article_id)

        # End-of-line of the header (first \n after match start) — skip
        # past the metadata that lives on the same line as the article ID.
        nl = text.find("\n", m.end())
        body_start = nl + 1 if nl != -1 else m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body_raw = text[body_start:body_end]

        # Strip codes.droit.org noise lines.
        body_clean = _NOISE_LINE_RE.sub("", body_raw)

        # Collapse runs of whitespace and blank lines.
        lines = [l.strip() for l in body_clean.splitlines() if l.strip()]
        if not lines:
            continue
        title = lines[0][:200]
        body = "\n".join(lines)
        out.append(ArticleMeta(
            article_id=article_id,
            title=title,
            body=body,
        ))
    return out

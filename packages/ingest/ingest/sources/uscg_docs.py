"""Shared helpers for U.S. government document collections (2026-09-30).

Used by uscg_cvc, uscg_towing, uscg_safety_alert, uscg_waterways and epa_vgp,
and by the NMC checklist and Medical Manual downloads. Each collection is a
listing page (or a fixed list) of PDFs:

  discover   the adapter turns a listing page into Doc entries (doc_id, title,
             URL, date) and writes them to <raw_dir>/index.json
  download   fetch_docs() saves each PDF as <raw_dir>/<filename>; a file already
             on disk is kept unless the listing's URL for it changed (a new
             "?ver=" token or revision) or it is older than refresh_days
  parse      doc_sections() gives one Section per document, or per part when
             the adapter passes a splitter; the chunker splits long ones

dco.uscg.mil and media.defense.gov sit behind Akamai. These browser headers
(the NVIC adapter's) get through from the VPS; plain clients get 403 from some
networks, so run discovery on the VPS (probe 2026-09-30).

All of these documents are U.S. government works (public domain).
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin

import httpx

from ingest.models import Section

logger = logging.getLogger(__name__)

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}
TIMEOUT = 90.0
REQUEST_DELAY = 1.0  # seconds between downloads


@dataclass
class Doc:
    doc_id: str                 # the section_number, e.g. "CG-CVC PL 21-03"
    title: str
    url: str
    filename: str               # stored as <raw_dir>/<filename>
    published: str | None = None  # ISO date
    note: str = ""              # e.g. "Supersedes PL 23-05"

    @property
    def published_date(self) -> date | None:
        return date.fromisoformat(self.published) if self.published else None


# ── Fetching ─────────────────────────────────────────────────────────────────

def client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, follow_redirects=True, headers=BROWSER_HEADERS)


def fetch_html(url: str, http: httpx.Client | None = None) -> str:
    own = http is None
    http = http or client()
    try:
        resp = http.get(url)
        resp.raise_for_status()
        return resp.text
    finally:
        if own:
            http.close()


def absolute(href: str, base: str) -> str:
    """An absolute URL for an href found on *base*; raw spaces become %20."""
    return urljoin(base, href.strip()).replace(" ", "%20")


def is_pdf_href(href: str) -> bool:
    """True for "….pdf", "….pdf?ver=…" and "….PDF#page=2"."""
    return href.split("?", 1)[0].split("#", 1)[0].lower().endswith(".pdf")


def safe_filename(text: str, suffix: str = ".pdf") -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("._") or "document"
    return name[:120] + ("" if name.lower().endswith(suffix) else suffix)


def download_file(url: str, path: Path, http: httpx.Client | None = None) -> bool:
    """Save *url* to *path*; True on success. A response that is not a PDF when
    *path* ends in .pdf (Akamai's HTML block page) counts as a failure."""
    own = http is None
    http = http or client()
    try:
        resp = http.get(url)
        resp.raise_for_status()
        body = resp.content
        if path.suffix.lower() == ".pdf" and not body.startswith(b"%PDF"):
            raise ValueError(f"not a PDF ({resp.headers.get('content-type', '?')}, {len(body)} bytes)")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(body)
        tmp.replace(path)
        return True
    except Exception as exc:
        logger.warning("download failed: %s — %s", url, exc)
        return False
    finally:
        if own:
            http.close()


def write_index(raw_dir: Path, docs: Iterable[Doc]) -> Path:
    """Save the listing as <raw_dir>/index.json, which parse_source reads.

    A listing under half the size of the saved one usually means the page
    layout changed, not that half the documents were withdrawn: the saved
    index is kept and a warning logged.
    """
    docs = list(docs)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / "index.json"
    if path.exists():
        previous = read_index(raw_dir)
        if len(docs) < len(previous) / 2:
            logger.warning(
                "%s: the listing gave %d documents, down from %d; keeping the saved index "
                "(the page layout may have changed)", raw_dir.name, len(docs), len(previous))
            return path
    path.write_text(json.dumps([asdict(d) for d in docs], indent=1), encoding="utf-8")
    return path


def read_index(raw_dir: Path) -> list[Doc]:
    path = raw_dir / "index.json"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run discovery first")
    return [Doc(**d) for d in json.loads(path.read_text(encoding="utf-8"))]


def fetch_docs(
    docs: list[Doc],
    raw_dir: Path,
    failed_dir: Path,
    source: str,
    *,
    refresh_days: int | None = None,
    console=None,
) -> tuple[int, int]:
    """Download every Doc not already current on disk. Returns (present, failed).

    A file is re-fetched when the listing's URL for it differs from the one it
    was downloaded from (tracked in <raw_dir>/downloaded.json), or when it is
    older than refresh_days (for publishers that revise files in place, e.g.
    the NMC checklists).
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    seen_path = raw_dir / "downloaded.json"
    seen: dict[str, str] = json.loads(seen_path.read_text(encoding="utf-8")) if seen_path.exists() else {}
    present = failed = 0
    fetched = 0
    now = time.time()
    with client() as http:
        for doc in docs:
            path = raw_dir / doc.filename
            stale = refresh_days is not None and path.exists() and (now - path.stat().st_mtime) > refresh_days * 86400
            if path.exists() and seen.get(doc.filename, doc.url) == doc.url and not stale:
                present += 1
                continue
            if fetched:
                time.sleep(REQUEST_DELAY)
            fetched += 1
            if download_file(doc.url, path, http):
                seen[doc.filename] = doc.url
                present += 1
            else:
                failed += 1
                failed_dir.mkdir(parents=True, exist_ok=True)
                (failed_dir / f"{source}_{safe_filename(doc.doc_id, '.json')}").write_text(
                    json.dumps(asdict(doc), indent=1), encoding="utf-8")
                if path.exists():
                    present += 1  # keep parsing the copy we had
    seen_path.write_text(json.dumps(seen, indent=1), encoding="utf-8")
    if console:
        console.print(f"  [cyan]{source}:[/cyan] {present} documents on disk, {fetched} fetched this run, {failed} failed")
    return present, failed


# ── Dates ────────────────────────────────────────────────────────────────────

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def parse_date(text: str) -> str | None:
    """ISO date from "9/23/2026", "2026-09-23", "01Jun26", "22APR24", "14 July 2026",
    "July 14, 2026"; None when nothing parses."""
    text = (text or "").strip()
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", text)
    if m:
        return _iso(int(m.group(3)), int(m.group(1)), int(m.group(2)))
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text)
    if m:
        return _iso(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"\b(\d{1,2})\s*([A-Za-z]{3})[a-z]*\.?\s*(\d{2}|\d{4})\b", text)
    if m and m.group(2).lower() in _MONTHS:
        year = int(m.group(3))
        return _iso(year + 2000 if year < 100 else year, _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.search(r"\b([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", text)
    if m and m.group(1).lower() in _MONTHS:
        return _iso(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def _iso(y: int, m: int, d: int) -> str | None:
    try:
        return date(y, m, d).isoformat()
    except ValueError:
        return None


# ── Text ─────────────────────────────────────────────────────────────────────

_PAGE_LINE = re.compile(r"^\s*(?:page\s+)?\d{1,4}(?:\s+of\s+\d{1,4})?\s*$", re.I)
_LEADER_LINE = re.compile(r"\.{6,}\s*\d*\s*$")  # table-of-contents leaders
_WORD = re.compile(r"\S{6,}")


def _untriple(match: re.Match) -> str:
    """"TTTOOOWWWIIINNNGGG" -> "TOWING": headings printed in overstruck bold
    (the NMC TOARs) extract with every character three times."""
    w = match.group(0)
    if len(w) % 3 == 0 and all(w[i] == w[i + 1] == w[i + 2] for i in range(0, len(w), 3)):
        return w[::3]
    return w


def untriple(text: str) -> str:
    """Every overstruck-bold word in *text* back to single letters."""
    return _WORD.sub(_untriple, text)


def pdf_text(path: Path) -> str:
    """Text of a PDF, page by page. pdfplumber first; pdftotext when pdfplumber
    returns nothing (some USCG PDFs are built in ways pdfplumber reads poorly)."""
    pages: list[str] = []
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            pages = [(page.extract_text() or "") for page in pdf.pages]
    except Exception as exc:
        logger.warning("pdfplumber failed on %s: %s", path.name, exc)
    text = "\f".join(pages)
    if len(text.strip()) < 200:
        try:
            text = subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True,
                                           stderr=subprocess.DEVNULL, timeout=300)
        except Exception:
            pass
    return text


def clean_text(text: str) -> str:
    """Drop page numbers, TOC leader lines and lines repeated on most pages
    (running headers and footers); collapse blank runs."""
    pages = text.split("\f")
    counts: dict[str, int] = {}
    for page in pages:
        for line in {ln.strip() for ln in page.splitlines() if ln.strip()}:
            counts[line] = counts.get(line, 0) + 1
    repeated = {ln for ln, n in counts.items() if len(pages) >= 4 and n >= max(3, len(pages) * 0.5) and len(ln) < 120}
    out: list[str] = []
    for page in pages:
        for line in page.splitlines():
            s = line.strip()
            if not s:
                if out and out[-1] != "":
                    out.append("")
                continue
            if s in repeated or _PAGE_LINE.match(s) or _LEADER_LINE.search(s):
                continue
            out.append(_WORD.sub(_untriple, re.sub(r"[ \t]+", " ", s)))
    return "\n".join(out).strip()


# ── Sections ─────────────────────────────────────────────────────────────────

Splitter = Callable[[Doc, str], list[tuple[str, str, str]]]  # -> [(section_number, title, body)]


def doc_sections(
    source: str,
    docs: list[Doc],
    raw_dir: Path,
    *,
    splitter: Splitter | None = None,
    default_date: date | None = None,
) -> list[Section]:
    """One Section per document on disk (or per part, with a splitter)."""
    sections: list[Section] = []
    for doc in docs:
        path = raw_dir / doc.filename
        if not path.exists():
            logger.warning("%s: %s not on disk (%s) — skipped", source, doc.doc_id, doc.filename)
            continue
        text = clean_text(pdf_text(path)) if path.suffix.lower() == ".pdf" else path.read_text(encoding="utf-8")
        if len(text) < 80:
            logger.warning("%s: %s gave no usable text — skipped", source, doc.doc_id)
            continue
        as_of = doc.published_date or default_date or date.today()
        title = f"{doc.doc_id} — {doc.title}" if doc.title else doc.doc_id
        if doc.note:
            title = f"{title} ({doc.note})"
        parts = splitter(doc, text) if splitter else []
        if not parts:
            parts = [(doc.doc_id, title, text)]
        for sec_num, sec_title, body in parts:
            if not body.strip():
                continue
            sections.append(Section(
                source=source,
                title_number=0,
                section_number=sec_num,
                section_title=sec_title[:500],
                full_text=body,
                up_to_date_as_of=as_of,
                parent_section_number=doc.doc_id if sec_num != doc.doc_id else None,
            ))
    logger.info("%s: %d sections from %d listed documents", source, len(sections), len(docs))
    return sections


def listing_source_date(raw_dir: Path) -> date:
    """Today, so an update run always parses.

    The update-mode short-circuit compares this date with the
    up_to_date_as_of of one stored row (store.get_previous_as_of, no ORDER
    BY). These sources date each document separately, CVC letters only by
    year, so any document date could skip a new document. Update mode's hash
    dedup does the change detection instead: only chunks whose text changed
    are embedded.
    """
    return date.today()


def rows(html: str, base: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """Every table row as ([cell texts], [(absolute href, link text) of its links])."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    out = []
    for tr in soup.find_all("tr"):
        cells = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tr.find_all(["td", "th"])]
        links = [(absolute(a["href"], base), re.sub(r"\s+", " ", a.get_text(" ", strip=True)))
                 for a in tr.find_all("a", href=True)]
        if cells:
            out.append((cells, links))
    return out


def links(html: str, base: str) -> list[tuple[str, str]]:
    """Every (absolute href, link text) on the page, in order, without duplicates."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    seen: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = absolute(a["href"], base)
        text = re.sub(r"\s+", " ", a.get_text(" ", strip=True))
        if href not in seen or (text and not seen[href]):
            seen[href] = text
    return list(seen.items())


def today_iso() -> str:
    return datetime.now().date().isoformat()

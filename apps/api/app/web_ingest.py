"""Ingest the official documents the phase-2 web research finds (2026-10-08).

Blake, 2026-10-08: "I think we ingest a legit hit." When the web research
answers a gap from an official document, that document joins the library
(source `web_ingest`), so the next mariner who asks gets it from the library,
cited and verified, without a web step. Spec: docs/specs/answer-pipeline-2026-10-08.md.

A hit is legit when:
  - the gap was found (corpus_gaps.status = 'found');
  - a source is on an official domain (INGEST_DOMAINS, the wildcard government
    suffixes): regulators, the IMO / ILO / IACS / EU, flag administrations and
    registries, classification societies. Commentary (P&I clubs, industry
    bodies, news) informs answers but is not ingested;
  - its quote was verified on the page at research time AND is found again in
    the text fetched here;
  - the text is 1,500-400,000 characters;
  - it isn't the CFR (ecfr.gov / govinfo / law.cornell.edu: the CFR is in the
    library in full and refreshed weekly) and its URL isn't already ingested.

Rows: source 'web_ingest', source_version = the URL, section_number
"{publisher}: {title}", jurisdictions by domain. Daily cap WEB_INGEST_DAILY_CAP.
app.tasks.ingest_web_gaps runs this every 15 minutes, a few gaps per run.
"""
from __future__ import annotations

import hashlib
import html as _html
import io
import logging
import re
from datetime import date
from urllib.parse import urlparse

import httpx

from app.company_docs import _vec, chunk_sections, embed_texts, split_sections

logger = logging.getLogger(__name__)

MIN_CHARS = 1_500
MAX_CHARS = 400_000
MAX_BYTES = 20 * 1024 * 1024
MAX_CHUNKS = 250
PER_RUN = 5

_SUFFIX_JURISDICTION: tuple[tuple[str, list[str]], ...] = (
    (".gov.uk", ["uk"]), (".gov.au", ["au"]), (".gov.sg", ["sg"]), (".gov.hk", ["hk"]),
    (".gc.ca", ["ca"]), (".canada.ca", ["ca"]), (".gov.cy", ["cy"]), (".gob.pa", ["pa"]),
    (".gov.it", ["it"]), (".gouv.fr", ["fr"]), (".gob.es", ["es"]), (".bund.de", ["de"]),
    (".gov.gr", ["gr"]), (".gov.no", ["no"]), (".gov", ["us"]), (".mil", ["us"]),
)
_DOMAIN_JURISDICTION: dict[str, list[str]] = {
    "gov.uk": ["uk"], "mca.gov.uk": ["uk"], "amsa.gov.au": ["au"], "mpa.gov.sg": ["sg"],
    "mardep.gov.hk": ["hk"], "tc.gc.ca": ["ca"], "tc.canada.ca": ["ca"], "sdir.no": ["no"],
    "register-iri.com": ["mh"], "registry-iri.com": ["mh"], "liscr.com": ["lr"],
    "bahamasmaritime.com": ["bs"], "amp.gob.pa": ["pa"], "panamashipregistry.com": ["pa"],
    "dms.gov.cy": ["cy"], "deutsche-flagge.de": ["de"], "bsh.de": ["de"], "guardiacostiera.gov.it": ["it"],
    "mit.gov.it": ["it"], "legifrance.gouv.fr": ["fr"], "ynanp.gr": ["gr"], "hcg.gr": ["gr"],
}
# Official sources whose documents may join the library (subdomains included).
INGEST_DOMAINS: frozenset[str] = frozenset({
    "imo.org", "ilo.org", "iacs.org.uk", "europa.eu", "who.int", "itu.int", "iho.int", "iala-aism.org",
    "eagle.org", "dnv.com", "lr.org", "bureauveritas.com", "classnk.or.jp", "rina.org", "krs.co.kr",
    "korean-register.or.kr", "ccs.org.cn", "irclass.org", "turkloydu.org", "prs.pl", "crs.hr",
    "uscg.mil", "tokyo-mou.org", "parismou.org",
    *_DOMAIN_JURISDICTION,
})
_SUFFIXES = tuple(s for s, _ in _SUFFIX_JURISDICTION)
_NOT_INGESTED = ("ecfr.gov", "govinfo.gov", "law.cornell.edu", "regulations.gov")


def _host(url: str) -> str:
    h = urlparse(url).netloc.lower().split(":")[0]
    return h[4:] if h.startswith("www.") else h


def _matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


def ingest_decision(url: str) -> str | None:
    """None when the URL's domain may be ingested, else the reason it isn't."""
    host = _host(url)
    if not host:
        return "no host"
    if any(_matches(host, d) for d in _NOT_INGESTED):
        return "CFR text is already in the library in full"
    if any(_matches(host, d) for d in INGEST_DOMAINS) or host.endswith(_SUFFIXES):
        return None
    return "not an official source (commentary is used in answers, not ingested)"


def jurisdictions_for(url: str) -> list[str]:
    host = _host(url)
    for d, j in _DOMAIN_JURISDICTION.items():
        if _matches(host, d):
            return j
    for suffix, j in _SUFFIX_JURISDICTION:
        if host.endswith(suffix):
            return j
    return ["intl"]


def pick_source(sources: list[dict]) -> tuple[dict | None, str]:
    """The first verified source on an ingestable domain, or (None, why not)."""
    why = "no verified quote on an official site"
    for s in sources or []:
        reason = ingest_decision(s.get("url") or "")
        if reason:
            why = reason
            continue
        if not s.get("verified"):
            why = "quote not verified on the page"
            continue
        return s, ""
    return None, why


_DROP_BLOCKS = re.compile(r"<(script|style|noscript|nav|header|footer|aside|form|svg|iframe)\b.*?</\1\s*>",
                          re.I | re.S)
_BREAKS = re.compile(r"</(p|div|li|tr|h[1-6]|section|article|table|ul|ol|blockquote)\s*>|<br\s*/?>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(raw: str) -> str:
    """Main content of an HTML page as plain text with paragraph breaks."""
    body = raw
    for tag in ("main", "article"):
        m = re.search(rf"<{tag}\b[^>]*>(.*?)</{tag}\s*>", raw, re.I | re.S)
        if m and len(m.group(1)) > 2000:
            body = m.group(1)
            break
    body = _DROP_BLOCKS.sub(" ", body)
    body = _BREAKS.sub("\n", body)
    text = _html.unescape(_TAGS.sub(" ", body))
    lines = [re.sub(r"[ \t\xa0]+", " ", ln).strip() for ln in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(ln for ln in lines if ln) )


async def fetch_pages(url: str) -> list[str]:
    """The document's text, one element per PDF page (one for HTML)."""
    async with httpx.AsyncClient(follow_redirects=True, timeout=30,
                                 headers={"User-Agent": "Mozilla/5.0 (compatible; RegKnot/1.0)"}) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    if len(resp.content) > MAX_BYTES:
        raise ValueError(f"document larger than {MAX_BYTES // 1024 // 1024} MB")
    ctype = (resp.headers.get("content-type") or "").lower()
    if "pdf" in ctype or resp.content[:5] == b"%PDF-":
        from pypdf import PdfReader
        return [(p.extract_text() or "") for p in PdfReader(io.BytesIO(resp.content)).pages]
    return [html_to_text(resp.text)]


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace("’", "'").replace("“", '"').replace("”", '"')).strip().lower()


def section_name(source: dict) -> str:
    who = (source.get("publisher") or source.get("domain") or _host(source.get("url", ""))).strip()
    title = re.sub(r"\s+", " ", source.get("title") or "").strip() or _host(source.get("url", ""))
    return f"{who}: {title}"[:200]


async def ingest_gap(pool, gap: dict, openai_api_key: str) -> tuple[str, str, str | None, str | None]:
    """(status, note, section, url) for one found gap; never raises."""
    import json
    sources = gap["sources"]
    if isinstance(sources, str):
        sources = json.loads(sources or "[]")
    src, why = pick_source(sources)
    if src is None:
        return "ingest_skipped", why, None, None
    url = src["url"]
    existing = await pool.fetchval(
        "SELECT section_number FROM regulations WHERE source = 'web_ingest' AND source_version = $1 LIMIT 1", url)
    if existing:
        return "ingested", "already in the library", existing, url
    try:
        pages = await fetch_pages(url)
    except Exception as exc:  # noqa: BLE001
        return "ingest_failed", f"fetch: {type(exc).__name__}: {str(exc)[:200]}", None, url
    text = "\n\n".join(pages)
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        return "ingest_skipped", f"text length {len(text)} outside {MIN_CHARS}-{MAX_CHARS}", None, url
    if src.get("quote") and _norm(src["quote"]) not in _norm(text):
        return "ingest_skipped", "quote not found in the fetched text", None, url
    name = section_name(src)
    clash = await pool.fetchval(
        "SELECT source_version FROM regulations WHERE source = 'web_ingest' AND section_number = $1 LIMIT 1", name)
    if clash and clash != url:
        name = f"{name[:190]} ({hashlib.sha1(url.encode()).hexdigest()[:6]})"
    chunks = chunk_sections(split_sections(pages))[:MAX_CHUNKS]
    if not chunks:
        return "ingest_skipped", "no text after splitting", None, url
    title = (src.get("title") or name)[:300]
    texts = [f"[{name}] {title}\n\n{heading}\n\n{body}".replace("\n\n\n\n", "\n\n") for heading, _, body in chunks]
    try:
        vectors = await embed_texts(texts, openai_api_key)
    except Exception as exc:  # noqa: BLE001
        return "ingest_failed", f"embed: {type(exc).__name__}: {str(exc)[:200]}", None, url
    publisher = (src.get("publisher") or src.get("domain") or _host(url))[:200]
    juris = jurisdictions_for(url)
    await pool.executemany(
        """
        INSERT INTO regulations (source, source_version, title, section_number, section_title, full_text,
                                 chunk_index, embedding, up_to_date_as_of, content_hash, jurisdictions, language)
        VALUES ('web_ingest', $1, $2, $3, $4, $5, $6, $7::vector, $8, $9, $10::text[], 'en')
        ON CONFLICT (source, section_number, chunk_index) DO NOTHING
        """,
        [(url, publisher, name, title, t, i, _vec(v), date.today(), hashlib.sha256(t.encode()).hexdigest(), juris)
         for i, (t, v) in enumerate(zip(texts, vectors))],
    )
    logger.info("web_ingest: %s (%d chunks, %s) from %s", name, len(texts), juris, url)
    return "ingested", f"{len(texts)} chunks, jurisdictions {juris}", name, url


async def run(pool, openai_api_key: str, daily_cap: int, per_run: int = PER_RUN) -> dict:
    """Process found gaps, oldest first, within the daily cap."""
    today = await pool.fetchval(
        "SELECT count(*) FROM corpus_gaps WHERE status = 'ingested' AND ingested_section IS NOT NULL "
        "AND ingest_note NOT LIKE 'already%' AND updated_at > now() - interval '1 day'")
    room = max(0, min(per_run, daily_cap - int(today or 0)))
    if not room:
        return {"processed": 0, "reason": "daily cap"}
    rows = await pool.fetch(
        """
        UPDATE corpus_gaps SET status = 'ingest_queued', updated_at = now()
        WHERE id IN (SELECT id FROM corpus_gaps WHERE status = 'found' ORDER BY created_at LIMIT $1
                     FOR UPDATE SKIP LOCKED)
        RETURNING id, sources
        """,
        room,
    )
    out: dict[str, int] = {}
    for gap in rows:
        try:
            status, note, section, url = await ingest_gap(pool, dict(gap), openai_api_key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("web_ingest gap %s failed", gap["id"])
            status, note, section, url = "ingest_failed", f"{type(exc).__name__}: {str(exc)[:200]}", None, None
        await pool.execute(
            "UPDATE corpus_gaps SET status = $2, ingest_note = $3, ingested_section = $4, "
            "ingest_url = COALESCE($5, ingest_url), updated_at = now() WHERE id = $1",
            gap["id"], status, note[:500], section, url,
        )
        out[status] = out.get(status, 0) + 1
    return {"processed": len(rows), **out}

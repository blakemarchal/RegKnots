"""
Web search fallback for the hedge path.

Sprint D6.48 Phase 1 — when our corpus genuinely lacks an answer
(retrieval top-1 cosine < 0.5 AND hedge classifier matches), we fire a
web search against a strict whitelist of regulator/standards-body
domains. The result is surfaced ONLY if all three gates pass:

  1. The cited URL is on the trusted-domain whitelist.
  2. Claude self-rated confidence is ≥ 4 of 5.
  3. The verbatim quote Claude cites can be located in the source's
     plaintext (after light normalization).

If any gate fails, the original hedge response stands. Every attempt is
logged to `web_fallback_responses` so we can audit retroactively and
identify gap sources to ingest as full RegKnots corpora.

Architecture:
  - This module exposes pure functions (whitelist matching, quote
    verification, normalization) plus the `attempt_web_fallback` async
    orchestrator that talks to Anthropic with the web_search tool.
  - It does NOT touch the chat pipeline directly; the pipeline imports
    `attempt_web_fallback` and invokes it at the hedge-detection point.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)


# ── Whitelist ────────────────────────────────────────────────────────────────
# Strict v1: only sources we'd cite as authoritative in an audit.
# Loosen by adding entries here, not by changing matching logic.

EXACT_TRUSTED_DOMAINS: frozenset[str] = frozenset({
    # IMO + IACS + EU regulators
    "imo.org",
    "iacs.org.uk",
    "emsa.europa.eu",
    "eumos.eu",
    # Class societies (IACS members)
    "bureauveritas.com",
    "marine-offshore.bureauveritas.com",
    "rulesexplorer-docs.bureauveritas.com",
    "dnv.com",
    "rules.dnv.com",
    "eagle.org",                       # ABS
    "ww2.eagle.org",
    "classnk.or.jp",
    "lr.org",                          # Lloyd's Register
    "rina.org",
    "krs.co.kr",
    "ccs.org.cn",                      # China Classification Society
    "irclass.org",                     # Indian Register
    "rs-class.org",                    # Russian Maritime Register
    # Standards bodies
    "iso.org",
    "itu.int",
    # US federal
    "uscg.mil",
    "homeport.uscg.mil",
    "dco.uscg.mil",
    "navcen.uscg.mil",
    "cgmix.uscg.mil",
    "ecfr.gov",
    "govinfo.gov",
    "regulations.gov",
    "epa.gov",
    "noaa.gov",
    "nws.noaa.gov",
    "nhc.noaa.gov",
    "phmsa.dot.gov",
    "tsa.gov",
    # National flag-state regulators (already in our corpus or candidates)
    "amsa.gov.au",
    "deutsche-flagge.de",
    "transportes.gob.es",
    "cdn.transportes.gob.es",
    "guardiacostiera.gov.it",
    "mit.gov.it",
    "lavoromarittimo.mit.gov.it",
    "ynanp.gr",
    "hcg.gr",
    "sdir.no",
    "mardep.gov.hk",
    "mpa.gov.sg",
    "bahamasmaritime.com",
    "register-iri.com",
    "registry-iri.com",
    "liscr.com",
    "tc.gc.ca",
    "tc.canada.ca",
    "mca.gov.uk",
    "gov.uk",
    # International marine MOUs
    "tokyo-mou.org",
    "parismou.org",
    "uscg.mil",
    "blacksea-mou.org",
    "caribbeanmou.org",
    # Industry bodies whose technical guidance is widely adopted
    "ics-shipping.org",
    "ocimf.org",
    "intertanko.com",
    "intercargo.org",
    "bimco.org",
    # WHO + IMO joint
    "who.int",
})

# Wildcard suffixes — entries here match any subdomain of the listed TLD.
WILDCARD_TRUSTED_SUFFIXES: tuple[str, ...] = (
    ".gov",
    ".mil",
    ".gov.au",
    ".gov.uk",
    ".gov.it",
    ".gov.hk",
    ".gov.sg",
    ".gov.bs",
    ".gob.es",
    ".gc.ca",
    ".canada.ca",
)


def normalize_domain(host: str) -> str:
    """Lowercase, strip leading 'www.'."""
    h = host.strip().lower()
    if h.startswith("www."):
        h = h[4:]
    return h


def is_trusted_domain(url: str) -> bool:
    """True if the URL's host is on the whitelist (exact or wildcard suffix)."""
    try:
        host = urlparse(url).netloc
    except Exception:
        return False
    if not host:
        return False
    h = normalize_domain(host)
    if h in EXACT_TRUSTED_DOMAINS:
        return True
    for suffix in WILDCARD_TRUSTED_SUFFIXES:
        if h.endswith(suffix):
            return True
    return False


# ── Quote validation ────────────────────────────────────────────────────────


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
    "RegKnots/1.0 (+https://regknots.com)"
)
_FETCH_HEADERS = {
    "User-Agent":      _USER_AGENT,
    "Accept":          "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
_FETCH_TIMEOUT_S = 25.0
_MAX_FETCH_BYTES = 20 * 1024 * 1024     # 20 MB cap for source extraction


_SMART_QUOTE_TABLE = str.maketrans({
    "“": '"', "”": '"',
    "‘": "'", "’": "'",
    "–": "-", "—": "-",
    " ": " ",
})

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_HTML_ENTITY_AMP = re.compile(r"&amp;",  re.IGNORECASE)
_HTML_ENTITY_LT  = re.compile(r"&lt;",   re.IGNORECASE)
_HTML_ENTITY_GT  = re.compile(r"&gt;",   re.IGNORECASE)
_HTML_ENTITY_NBSP = re.compile(r"&nbsp;", re.IGNORECASE)
_HTML_ENTITY_QUOT = re.compile(r"&quot;", re.IGNORECASE)
_HTML_ENTITY_APOS = re.compile(r"&apos;", re.IGNORECASE)
_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Light normalization for quote matching:
      - lowercase
      - smart quotes → straight, em/en-dash → hyphen, nbsp → space
      - collapse all whitespace runs to a single space
    Designed to be aggressive enough that PDF re-flow + HTML markup
    don't break a verbatim match, but conservative enough not to false-
    positive (e.g. we DON'T strip punctuation or normalize numbers).
    """
    s = s.translate(_SMART_QUOTE_TABLE)
    s = _WHITESPACE_RUN.sub(" ", s)
    return s.strip().lower()


def _strip_html(html: str) -> str:
    s = _HTML_TAG_RE.sub(" ", html)
    s = _HTML_ENTITY_NBSP.sub(" ", s)
    s = _HTML_ENTITY_AMP.sub("&", s)
    s = _HTML_ENTITY_LT.sub("<", s)
    s = _HTML_ENTITY_GT.sub(">", s)
    s = _HTML_ENTITY_QUOT.sub('"', s)
    s = _HTML_ENTITY_APOS.sub("'", s)
    return s


async def fetch_source_text(url: str, client: httpx.AsyncClient) -> str:
    """Download and extract plaintext from a URL. Handles both HTML and
    PDF responses based on Content-Type. Returns "" if the source is
    unreachable or oversized. Never raises — failure → empty string,
    which means quote verification fails closed."""
    try:
        resp = await client.get(url, headers=_FETCH_HEADERS,
                                timeout=_FETCH_TIMEOUT_S,
                                follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        logger.info("Source fetch failed %s: %s", url, exc)
        return ""

    if len(resp.content) > _MAX_FETCH_BYTES:
        logger.info("Source too large %s (%d bytes)", url, len(resp.content))
        return ""

    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "pdf" in ctype or resp.content[:4] == b"%PDF":
        # PDF: extract via pdfplumber to a single concatenated string.
        # Lazy import — pdfplumber isn't on the API container's dep list,
        # but it IS available on the ingest container; if a user-facing
        # invocation hits a PDF source on a host without pdfplumber, we
        # fall through to writing the bytes to a temp file and shelling
        # out to Poppler's pdftotext (which is installed system-wide).
        try:
            from io import BytesIO
            try:
                import pdfplumber  # type: ignore
            except ImportError:
                pdfplumber = None
            if pdfplumber is not None:
                page_texts: list[str] = []
                with pdfplumber.open(BytesIO(resp.content)) as pdf:
                    for page in pdf.pages:
                        t = page.extract_text() or ""
                        page_texts.append(t)
                return "\n".join(page_texts)
            else:
                import subprocess, tempfile
                with tempfile.NamedTemporaryFile(
                    suffix=".pdf", delete=False
                ) as fh:
                    fh.write(resp.content)
                    pdf_path = fh.name
                try:
                    out = subprocess.run(
                        ["pdftotext", "-layout", pdf_path, "-"],
                        capture_output=True, timeout=30, check=True,
                    )
                    return out.stdout.decode("utf-8", errors="replace")
                finally:
                    import os as _os
                    try:
                        _os.unlink(pdf_path)
                    except OSError:
                        pass
        except Exception as exc:
            logger.info("PDF extract failed %s: %s", url, exc)
            return ""

    # Default: HTML / plain text. Strip tags + decode entities.
    try:
        html = resp.text
    except Exception:
        return ""
    return _strip_html(html)


async def verify_quote_in_source(
    quote: str,
    url: str,
    client: httpx.AsyncClient,
) -> bool:
    """True iff a normalized version of `quote` appears in the source's
    extracted plaintext. Returns False on any error (fetch fail, unable
    to extract, oversized, etc.) — fails closed."""
    if not quote or not quote.strip():
        return False
    source_text = await fetch_source_text(url, client)
    if not source_text:
        return False
    return normalize_text(quote) in normalize_text(source_text)


# ── Result dataclass ────────────────────────────────────────────────────────


@dataclass
class FallbackResult:
    """Outcome of a single fallback attempt — surfaced or not, plus all
    the metadata we want to log to web_fallback_responses."""
    query:                  str
    web_query_used:         Optional[str] = None
    top_urls:               list[str] = field(default_factory=list)
    confidence:             Optional[int] = None
    source_url:             Optional[str] = None
    source_domain:          Optional[str] = None
    quote_text:             Optional[str] = None
    quote_verified:         bool = False
    answer_text:            Optional[str] = None
    surfaced:               bool = False
    surface_blocked_reason: Optional[str] = None
    latency_ms:             int = 0


# ── Orchestrator: Anthropic web_search call + gating ─────────────────────────


# JSON schema we ask Claude to fill in. Keeping it explicit so the gates
# downstream have unambiguous fields to check.
_FALLBACK_SYSTEM_PROMPT = """You are a maritime regulatory research assistant. The user has a question that the RegKnots corpus could not answer with high confidence. Your job is to search authoritative public sources for an answer.

Use the web_search tool to find an answer from a regulator, classification society, or international standards body. Prefer primary sources (regulator's own published PDF or web page) over commentary or third-party summaries.

You MUST return a JSON object (and ONLY the JSON object, no prose around it) with these fields:
  - "confidence": integer 1-5 (5 = certain the answer is correct and matches the user's question; 1 = guessing)
  - "source_url": the URL of the single best source
  - "quote": a verbatim string from the source — copy exact wording, do not paraphrase. If you cannot find a verbatim sentence that supports the answer, return null.
  - "summary": a brief plain-English explanation (≤ 200 words) that interprets the quote for the user
  - "answer": the direct answer to the user's question, anchored on the quote
  - "search_query": the query you used (so we can audit)

Strict rules:
  1. The quote MUST be verbatim — exact wording from the source. We will verify it programmatically. If you can't find a verbatim sentence, return null for quote and confidence ≤ 2.
  2. If no authoritative source has the answer, return confidence ≤ 2.
  3. Never invent URLs. Only cite URLs that web_search actually returned.
  4. The user is a maritime professional — domain accuracy matters more than completeness.
"""


async def attempt_web_fallback(
    *,
    query: str,
    anthropic_client,
    model: str = "claude-sonnet-4-6",
    min_confidence: int = 4,
) -> FallbackResult:
    """Run one fallback attempt for a user query. Returns a FallbackResult
    with `surfaced=True` only if all gates pass.

    This function does NOT mutate any database; the caller is responsible
    for logging the result to web_fallback_responses.
    """
    started = time.monotonic()
    result = FallbackResult(query=query)

    try:
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=2048,
            system=_FALLBACK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }],
        )
    except Exception as exc:
        logger.warning("Web fallback API call failed: %s: %s",
                       type(exc).__name__, str(exc)[:200])
        result.surface_blocked_reason = "error"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    # Concatenate any text blocks from the response — the JSON should
    # be in the final text block after tool calls resolved.
    payload = _extract_final_json(response)
    if payload is None:
        result.surface_blocked_reason = "no_results"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    result.web_query_used = payload.get("search_query") or query
    result.confidence = _safe_int(payload.get("confidence"))
    result.source_url = payload.get("source_url")
    result.quote_text = payload.get("quote")
    result.answer_text = payload.get("answer") or payload.get("summary")
    result.top_urls = _collect_urls_from_response(response)[:3]

    if result.source_url:
        result.source_domain = normalize_domain(
            urlparse(result.source_url).netloc
        )

    # Gate 1: confidence floor
    if result.confidence is None or result.confidence < min_confidence:
        result.surface_blocked_reason = "low_confidence"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    # Gate 2: domain on whitelist
    if not result.source_url or not is_trusted_domain(result.source_url):
        result.surface_blocked_reason = "domain_blocked"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    # Gate 3: verbatim quote present in source
    if not result.quote_text:
        result.surface_blocked_reason = "quote_unverified"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    async with httpx.AsyncClient() as client:
        result.quote_verified = await verify_quote_in_source(
            result.quote_text, result.source_url, client,
        )
    if not result.quote_verified:
        result.surface_blocked_reason = "quote_unverified"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    # All gates passed.
    result.surfaced = True
    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


# ── Internal: parsing the Anthropic response shape ──────────────────────────


def _extract_final_json(response) -> Optional[dict]:
    """Pull the JSON object out of the assistant's text content. The
    web_search tool emits server_tool_use + web_search_tool_result blocks
    interleaved; the model's final answer is in the last 'text' block."""
    final_text = ""
    try:
        for block in response.content:
            if getattr(block, "type", None) == "text":
                final_text = block.text  # last text block wins
    except Exception:
        return None

    if not final_text:
        return None

    # Allow either a bare JSON object or fenced ```json ... ``` block.
    final_text = final_text.strip()
    if final_text.startswith("```"):
        # Strip first and last fence lines.
        lines = final_text.splitlines()
        if len(lines) >= 3:
            final_text = "\n".join(lines[1:-1])
    # Find the first { and matching close.
    start = final_text.find("{")
    end = final_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(final_text[start:end + 1])
    except json.JSONDecodeError as exc:
        logger.info("Fallback JSON parse failed: %s; text was: %s",
                    exc, final_text[:300])
        return None


def _collect_urls_from_response(response) -> list[str]:
    """Walk all tool-result blocks for any URLs we observed."""
    urls: list[str] = []
    try:
        for block in response.content:
            btype = getattr(block, "type", None)
            if btype == "web_search_tool_result":
                # Anthropic returns search results as an array of
                # objects with .url / .title / .page_age; iterate
                # defensively in case the shape evolves.
                content = getattr(block, "content", None) or []
                for item in content:
                    u = getattr(item, "url", None)
                    if u and isinstance(u, str):
                        urls.append(u)
    except Exception:
        pass
    return urls


def _safe_int(v) -> Optional[int]:
    try:
        if v is None:
            return None
        return int(v)
    except (ValueError, TypeError):
        return None

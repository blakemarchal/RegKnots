"""Web research for the items the library doesn't cover (2026-10-08, phase 2).

rag.coverage names what the library text lacks; this module looks each item up
on official websites before the answer is written, so the answer is written
once, with library citations and web sources side by side, instead of a hedge
followed by a card. Spec: docs/specs/answer-pipeline-2026-10-08.md.

  - One call per missing item (≤ 3, in parallel) to RESEARCH_MODEL with the
    basic `web_search_20250305` tool (the 2026 dynamic-filtering variant took
    40 s with nothing usable on 2026-09-22), max 3 searches.
  - Only sources on rag.web_fallback's allowlist count; each quote is checked
    on its page (8 s cap). An unverified quote is kept but marked.
  - The whole step has RESEARCH_BUDGET_S; an item still running is NOT FOUND.
  - Fail-closed per item: any error means NOT FOUND, never an exception.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

import httpx

from rag.web_fallback import (
    _extract_final_json,
    fetch_source_text,
    is_trusted_domain,
    normalize_domain,
    normalize_text,
)

logger = logging.getLogger(__name__)

RESEARCH_MODEL = os.environ.get("WEB_RESEARCH_MODEL") or "claude-haiku-5-5"
RESEARCH_BUDGET_S = 25.0
VERIFY_TIMEOUT_S = 8.0
MAX_SEARCHES = 3

_SYSTEM = """You research one specific fact for a maritime compliance assistant, using the web_search \
tool. Prefer the primary source: the regulator's or the IMO's own page or PDF, the eCFR, the Federal \
Register, a flag administration, a classification society. Commentary (P&I clubs, industry bodies) is \
acceptable when no primary source states the fact.

Return ONLY a JSON object, no prose around it:
{"found": true or false,
 "answer": "the fact, in at most 120 words, with exact figures, dates and section numbers as the source states them",
 "sources": [{"url": "...", "title": "...", "publisher": "...", "quote": "a verbatim sentence from that page"}]}

Rules: at most 3 sources, best first. Only URLs the search returned. The quote must be copied exactly, \
because it is checked programmatically. If no source states the fact, return found false and empty sources. \
Never guess: a wrong date or number is worse than found false."""


@dataclass
class WebSource:
    url: str
    title: str
    publisher: str
    domain: str
    quote: str
    verified: bool = False
    label: str = ""


@dataclass
class Finding:
    item: str
    search_query: str
    found: bool = False
    answer: str = ""
    sources: list[WebSource] = field(default_factory=list)
    latency_ms: int = 0
    error: str | None = None


def _clean(s: str, n: int) -> str:
    return re.sub(r"[\[\]\s]+", " ", s or "").strip()[:n]


async def _verify(src: WebSource, client: httpx.AsyncClient) -> None:
    if not src.quote:
        return
    try:
        text = await asyncio.wait_for(fetch_source_text(src.url, client), timeout=VERIFY_TIMEOUT_S)
    except Exception:  # noqa: BLE001 — timeout or fetch failure: unverified
        return
    src.verified = bool(text) and normalize_text(src.quote) in normalize_text(text)


async def research_item(client, *, item: str, search_query: str, question: str, vessel: str = "") -> Finding:
    from rag.llm import messages_create
    started = time.monotonic()
    f = Finding(item=item, search_query=search_query)
    prompt = (f"The mariner asked: {question}\n" + (f"Their vessel: {vessel}\n" if vessel else "")
              + f"Find this fact: {item}\nSuggested search: {search_query}")
    try:
        response = await messages_create(
            client, model=RESEARCH_MODEL, max_tokens=4096, output_config={"effort": "low"},
            system=_SYSTEM, messages=[{"role": "user", "content": prompt}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES}],
        )
        data = _extract_final_json(response) or {}
    except Exception as exc:  # noqa: BLE001
        f.error = f"{type(exc).__name__}: {str(exc)[:160]}"
        f.latency_ms = int((time.monotonic() - started) * 1000)
        return f
    for s in (data.get("sources") or [])[:3]:
        url = str(s.get("url") or "")
        if not url.startswith("http") or not is_trusted_domain(url):
            continue
        f.sources.append(WebSource(
            url=url, title=_clean(str(s.get("title") or ""), 90) or normalize_domain(urlparse(url).netloc),
            publisher=_clean(str(s.get("publisher") or ""), 60), domain=normalize_domain(urlparse(url).netloc),
            quote=str(s.get("quote") or "").strip()[:400]))
    f.found = bool(data.get("found")) and bool(f.sources)
    f.answer = str(data.get("answer") or "").strip()[:900] if f.found else ""
    if f.sources:
        async with httpx.AsyncClient() as http:
            await asyncio.gather(*(_verify(s, http) for s in f.sources))
    f.latency_ms = int((time.monotonic() - started) * 1000)
    return f


async def research(client, items, *, question: str, vessel: str = "",
                   budget_s: float = RESEARCH_BUDGET_S) -> list[Finding]:
    """Research every missing item in parallel within the budget; order kept."""
    tasks = [asyncio.create_task(research_item(client, item=i.item, search_query=i.search_query,
                                               question=question, vessel=vessel)) for i in items]
    if not tasks:
        return []
    done, pending = await asyncio.wait(tasks, timeout=budget_s)
    for t in pending:
        t.cancel()
    out: list[Finding] = []
    for i, t in zip(items, tasks):
        if t in done and not t.cancelled() and t.exception() is None:
            out.append(t.result())
        else:
            out.append(Finding(item=i.item, search_query=i.search_query, error="timeout"))
    _assign_labels(out)
    return out


def _assign_labels(findings: list[Finding]) -> None:
    seen: set[str] = set()
    for f in findings:
        for s in f.sources:
            base = f"Web: {s.domain} — {_clean(s.title, 70)}"
            label, n = base, 2
            while label in seen:
                label, n = f"{base} ({n})", n + 1
            seen.add(label)
            s.label = label


def format_block(findings: list[Finding]) -> str | None:
    """The WEB FINDINGS block for the answer model (folded into context_str)."""
    if not findings:
        return None
    parts = [
        "WEB FINDINGS — researched for this question on official websites because the library text "
        "above does not cover these points. They are current public sources, not RegKnot's library. "
        "Cite a finding exactly as its label reads, e.g. [Web: uscg.mil — Title], next to the statement "
        "it supports. A quote marked (not verified on the page) could not be matched on the page: use it "
        "only with its source named. For an item marked NOT FOUND, say in one plain sentence that you "
        "could not confirm it and give the most useful next step (who to ask, what to pull)."
    ]
    for n, f in enumerate(findings, 1):
        lines = [f"{n}. Needed: {f.item}"]
        if f.found:
            lines.append(f"   Found: {f.answer}")
            for s in f.sources:
                lines.append(f"   [{s.label}] {s.url}")
                if s.quote:
                    mark = "verified on the page" if s.verified else "not verified on the page"
                    lines.append(f'   Quote: "{s.quote}" ({mark})')
        else:
            lines.append("   NOT FOUND on official websites.")
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def sources_payload(findings: list[Finding]) -> list[dict]:
    """What the client shows and stores (messages.web_sources)."""
    return [{"label": s.label, "url": s.url, "title": s.title, "publisher": s.publisher, "domain": s.domain,
             "verified": s.verified, "item": f.item}
            for f in findings if f.found for s in f.sources]


def findings_payload(findings: list[Finding]) -> list[dict]:
    """Everything the gap log keeps (corpus_gaps)."""
    return [{"item": f.item, "search_query": f.search_query, "found": f.found, "answer": f.answer,
             "error": f.error, "latency_ms": f.latency_ms,
             "sources": [{"label": s.label, "url": s.url, "title": s.title, "publisher": s.publisher,
                          "domain": s.domain, "quote": s.quote, "verified": s.verified} for s in f.sources]}
            for f in findings]


def externally_sourced(text: str, findings: list[Finding]) -> bool:
    """True when a citation string appears in a finding (so the corpus verifier
    shouldn't strip it): the web source supports it even if the library lacks it."""
    hay = normalize_text(" ".join(f"{f.answer} " + " ".join(s.quote + " " + s.title for s in f.sources)
                                  for f in findings if f.found))
    return bool(text) and normalize_text(text) in hay

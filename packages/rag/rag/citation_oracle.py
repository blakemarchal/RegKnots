"""Citation oracle — Sprint D6.70.

Layer-2 retrieval intervention: when our corpus retrieval misses
(hedge classifier fires), we query the web for a citation hint
BEFORE falling back to the full ensemble. The oracle's job is
narrow:

    "Given this user question, what exact CFR / SOLAS / MARPOL
     section is most likely to contain the answer?"

The oracle does NOT answer the question. It returns a structured
citation pointer. We then look up that section in OUR corpus and
re-generate the answer from verified corpus text.

Architectural framing:

  Today's pipeline conflates routing and answering into one
  embedding pass. The web is dramatically better at routing
  (decades of PageRank + citation graph linking Cornell LII,
  ecfr.gov, USCG NMC, etc. for any regulation question) but
  offers no citation discipline. Our corpus is dramatically
  better at verbatim answers but routes only as well as our
  embedding similarity allows.

  Splitting the two roles — web does routing, corpus does
  answering — gives us both halves of what general AI does well
  AND what we do well, without giving up either.

Failure modes:

  - Web returns a citation we don't have in corpus → caller
    falls through to today's web fallback (existing behavior).
  - Web returns no citation → same fallthrough.
  - Oracle API fails → same fallthrough.
  - Oracle returns nonsense → caller verifies citation matches
    a real corpus chunk before re-generating.

In every failure case, behavior degrades to today's
hedge-then-fallback, never worse.

Cost: one Haiku call with web_search per intervention. Only
fires on hedge. ~$0.002, ~1.5-2.5s.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# Haiku 4.5 supports the web_search tool. Cheap routing model that's
# good at citation lookup; we don't need Sonnet's reasoning depth
# for "which CFR section answers this."
_ORACLE_MODEL = "claude-haiku-4-5-20251001"

# Tight token budget — the oracle returns a small JSON object, not prose.
_ORACLE_MAX_TOKENS = 600


_ORACLE_SYSTEM_PROMPT = """You are a maritime regulatory citation oracle. Given a user's question, search the web and identify the SINGLE CFR / SOLAS / MARPOL / STCW / NVIC section that most directly contains the answer.

Your job is narrow: identify the citation. Do NOT answer the question, do NOT summarize the regulation, do NOT include explanatory prose.

Hard rules:
  1. Return ONE primary citation in the canonical format the user's question implies. Use:
       "46 CFR 138.305"           for U.S. CFR
       "33 CFR 144.01-25"         for U.S. CFR with hyphenated subparts
       "SOLAS Ch.II-2 Reg.10"     for SOLAS
       "MARPOL Annex I Reg.14"    for MARPOL
       "STCW A-VI/1"              for STCW endorsements
       "NVIC 04-08"               for NVIC numbers
  2. Optionally include up to 2 alt_citations if multiple sections are relevant. The PRIMARY should be the single best match.
  3. Confidence:
       'high'   — search results agree on this exact section (e.g., Cornell LII, ecfr.gov both cite it)
       'medium' — likely but not certain
       'low'    — guess based on keywords; user should verify
  4. If no clear regulatory citation answers the question (e.g., the question is conversational or the answer lives in non-regulatory guidance), return primary_citation: null.
  5. Never invent a section number. If web search returns nothing on-target, return null.

Output JSON only — no prose, no markdown fences:

{
  "primary_citation": "46 CFR 138.305" | null,
  "alt_citations": ["46 CFR 138.310", "46 CFR 138.315"],
  "confidence": "high" | "medium" | "low",
  "reasoning": "1 sentence on what made you pick this section"
}
"""


# Citation patterns we accept — deliberate allow-list. Anything else
# returned by the oracle gets dropped (conservative — we don't want
# to inject malformed identifiers into the retrieval pipeline).
_VALID_CITATION_PATTERNS = (
    # CFR — e.g., "46 CFR 138.305", "33 CFR 144.01-25", "46 CFR 161.010-2"
    re.compile(r"^\d{1,2}\s+CFR\s+\d+(?:\.[\dT]+(?:-\d+)?)?$", re.IGNORECASE),
    # SOLAS — "SOLAS Ch.II-2 Reg.10", "SOLAS Ch.III Reg 19", "SOLAS Ch.II-1"
    re.compile(r"^SOLAS\s+Ch\.?\s*[IVX]+(?:-\d+)?(?:\s+Reg\.?\s*\d+(?:\.\d+)?)?$", re.IGNORECASE),
    # MARPOL — "MARPOL Annex I Reg.14"
    re.compile(r"^MARPOL\s+Annex\s+[IVX]+(?:\s+Reg\.?\s*\d+(?:\.\d+)?)?$", re.IGNORECASE),
    # STCW — "STCW A-VI/1", "STCW II/1"
    re.compile(r"^STCW\s+[A-Z]?-?[IVX]+/\d+$", re.IGNORECASE),
    # NVIC — "NVIC 04-08"
    re.compile(r"^NVIC\s+\d{2}-\d{2}$", re.IGNORECASE),
    # ISM Code section — "ISM 10.1", "ISM Code 11.3"
    re.compile(r"^ISM(?:\s+Code)?\s+\d+(?:\.\d+)?$", re.IGNORECASE),
)


@dataclass
class CitationHint:
    """Output of the citation oracle."""
    primary_citation: Optional[str]
    alt_citations: list[str] = field(default_factory=list)
    confidence: str = "low"   # 'high' | 'medium' | 'low'
    reasoning: str = ""
    raw_response: str = ""
    error: Optional[str] = None
    latency_ms: int = 0

    @property
    def has_citation(self) -> bool:
        return bool(self.primary_citation)


def _is_valid_citation(citation: str) -> bool:
    """Filter out citations the oracle returned that don't match our
    structured-citation patterns. Anything that fails this check gets
    dropped before we try to look it up in corpus — prevents nonsense
    strings from poisoning the retrieval-by-citation lookup."""
    if not citation:
        return False
    return any(p.match(citation.strip()) for p in _VALID_CITATION_PATTERNS)


async def find_citation_hint(
    query: str,
    anthropic_client,
) -> CitationHint:
    """Ask Haiku-with-web-search to identify the single best CFR /
    SOLAS / MARPOL section that answers the user's question.

    Failure-safe: any error returns CitationHint with primary_citation=None.
    Caller should treat None as "fall through to today's behavior."
    """
    import time
    started = time.monotonic()

    try:
        response = await anthropic_client.messages.create(
            model=_ORACLE_MODEL,
            max_tokens=_ORACLE_MAX_TOKENS,
            system=_ORACLE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query[:1500]}],
            # Same web_search tool the cascade ensemble uses for its
            # Claude probe. Up to 3 searches per oracle call.
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }],
        )
        text = "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", None) == "text"
        )
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.info("citation_oracle call failed (degrading to fallback): %s", err)
        return CitationHint(
            primary_citation=None,
            error=err,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    parsed = _parse_json(text)
    latency = int((time.monotonic() - started) * 1000)

    if parsed is None:
        logger.info(
            "citation_oracle returned no JSON (degrading): %s",
            text[:200],
        )
        return CitationHint(
            primary_citation=None,
            raw_response=text[:1000],
            error="no_json_in_response",
            latency_ms=latency,
        )

    primary = parsed.get("primary_citation")
    if primary is not None and not isinstance(primary, str):
        primary = None
    if primary:
        primary = primary.strip()
        if not _is_valid_citation(primary):
            logger.info(
                "citation_oracle returned malformed citation %r — dropping",
                primary,
            )
            primary = None

    alts_raw = parsed.get("alt_citations") or []
    alts: list[str] = []
    if isinstance(alts_raw, list):
        for a in alts_raw[:3]:
            if isinstance(a, str) and _is_valid_citation(a.strip()):
                alts.append(a.strip())

    confidence = (parsed.get("confidence") or "low").strip().lower()
    if confidence not in ("high", "medium", "low"):
        confidence = "low"

    reasoning = str(parsed.get("reasoning") or "").strip()[:300]

    logger.info(
        "citation_oracle: primary=%r alts=%s conf=%s latency_ms=%d",
        primary, alts, confidence, latency,
    )

    return CitationHint(
        primary_citation=primary,
        alt_citations=alts,
        confidence=confidence,
        reasoning=reasoning,
        raw_response=text[:1000],
        latency_ms=latency,
    )


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None

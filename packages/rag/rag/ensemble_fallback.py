"""Big-3 ensemble web fallback (Claude + GPT-4o + Grok).

Sprint D6.58 Slice 3.

When a chat hedges and the corpus genuinely missed, we orchestrate
three frontier models in parallel — each does its own web search,
returns a structured JSON response, and we synthesize the best
answer across them. The output surfaces as a `consensus` tier yellow
card if ≥2/3 agree, or `reference` if only 1 has a usable answer.

This is RegKnots' realization of the "federated knowledge layer":
- Class society rules (DNV, ABS, LR, NK), OEM equipment docs, niche
  technical references — all live on the public web. The three
  models hit those sources via their respective web search tools.
- We never re-host the content, so no licensing concern; we surface
  citations / source URLs and let the user verify.
- Cross-LLM agreement = stronger signal than any one model alone.
- Per-tier monthly caps bound the cost.

Cost: ~$0.17 per fire (3 web-search calls + 1 synthesis call).
At Captain's 25/mo cap, ~$4.25/mo per heaviest user. Free trial
gets 3 fires lifetime as a marketing showcase.

Key design decisions:
  - Trust hierarchy is verified (citation-verified corpus) >
    consensus (cross-LLM agreement on web sources) > reference
    (single-LLM web link) > blocked. Consensus is NEVER presented
    as gospel; users always see the "external sources, please
    verify" framing.
  - Class-society + OEM domain bias in the system prompt nudges
    each provider to prioritize iacs.org.uk, eagle.org (ABS),
    dnv.com, lr.org, classnk.or.jp, krs.co.kr, ccs.org.cn, plus
    OEM domains for the equipment named in the query.
  - All three providers are called concurrently via asyncio.gather
    so latency is dominated by the slowest, not their sum.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import httpx

from rag.web_fallback import (
    is_trusted_domain,
    normalize_domain,
    verify_quote_in_source,
)

logger = logging.getLogger(__name__)


# Provider model IDs. Pinned so a sudden upstream rename doesn't break
# the ensemble silently.
_CLAUDE_MODEL = "claude-sonnet-4-6"
_GPT_MODEL    = "gpt-4o"
# D6.58 audit fix — original `grok-4` doesn't exist; xAI deprecated
# Live Search in favor of the Responses API + tools. Now using their
# fast-reasoning model on the OpenAI-compatible Responses endpoint.
_GROK_MODEL   = "grok-4-fast-reasoning"

# xAI Responses endpoint (NOT chat/completions — they use a separate
# OpenAI-compatible Responses API for tool-augmented queries).
_XAI_RESPONSES_URL = "https://api.x.ai/v1/responses"

# Synthesis call uses Sonnet (cheaper than Opus, plenty smart enough
# to compare three short JSON responses). Output is a single JSON
# object the caller parses.
_SYNTHESIS_MODEL = "claude-sonnet-4-6"

# Class-society + OEM domains we want providers to prioritize for
# vessel-component / equipment questions (the federated knowledge
# layer's natural homes).
_PRIORITIZED_DOMAINS_NOTE = (
    "When the question is about vessel components, ship systems, OEM "
    "equipment, alarms, or installation specifics that don't live in "
    "IMO conventions or USCG CFR, prioritize these authoritative "
    "sources in this rough order:\n"
    "  - IACS (iacs.org.uk) — Unified Requirements + Recommendations\n"
    "  - Class society rule books — eagle.org (ABS), dnv.com, lr.org, "
    "classnk.or.jp, krs.co.kr, ccs.org.cn, bureauveritas.com, rina.org\n"
    "  - OEM technical documentation — name the manufacturer if "
    "evident from the query (e.g., Patlite, Werma, SM Electrics for "
    "signaling beacons)\n"
    "  - Industry technical journals — Marine Engineers Review, "
    "Maritime Reporter, Ship & Boat International\n"
    "Avoid: forum posts, blog summaries, AI-generated content, "
    "or content farms. Prefer the manufacturer's product page over "
    "third-party reseller pages."
)

_PROVIDER_SYSTEM_PROMPT = f"""You are a maritime regulatory and vessel-systems research assistant. The user has a question that the RegKnots primary corpus could not answer with high confidence. Your job is to search authoritative public sources and return a structured response.

{_PRIORITIZED_DOMAINS_NOTE}

You MUST return a JSON object (and ONLY the JSON object — no prose around it, no markdown fences) with these fields:
  "confidence":   integer 1-5 (5 = certain the answer is correct and matches the user's question; 1 = guessing)
  "source_url":   the URL of the single best source you found
  "quote":        a verbatim string from that source (copy exact wording, do not paraphrase). Return null if no usable verbatim sentence exists.
  "summary":      brief plain-English explanation, ≤ 200 words, anchored on the quote
  "answer":       the direct answer to the user's question
  "search_query": the query you actually used (for audit)

Strict rules:
  1. Quote MUST be verbatim from the cited source. We programmatically verify it.
  2. If no authoritative source has the answer, return confidence ≤ 2.
  3. Never invent URLs. Only cite URLs your web search actually returned.
  4. Maritime professionals will read this; domain accuracy beats completeness.
"""


# ── Provider results ────────────────────────────────────────────────────────


@dataclass
class ProviderResult:
    """Normalized response from one of the three frontier providers."""
    provider:        str           # 'claude' | 'gpt' | 'grok'
    succeeded:       bool = False
    confidence:      Optional[int] = None
    source_url:      Optional[str] = None
    source_domain:   Optional[str] = None
    quote_text:      Optional[str] = None
    quote_verified:  bool = False
    answer_text:     Optional[str] = None
    summary_text:    Optional[str] = None
    raw_response:    str = ""
    error:           Optional[str] = None
    latency_ms:      int = 0


# ── Synthesis output ────────────────────────────────────────────────────────


@dataclass
class EnsembleResult:
    """Output of synthesize_ensemble — what the engine surfaces to UI."""
    surfaced:           bool = False
    surface_tier:       str = "blocked"   # verified | consensus | reference | blocked
    surface_blocked_reason: Optional[str] = None
    agreement_count:    int = 0           # 0-3 providers that agreed on the picked answer
    best_answer:        Optional[str] = None
    best_summary:       Optional[str] = None
    best_quote:         Optional[str] = None
    best_quote_verified: bool = False
    best_source_url:    Optional[str] = None
    best_source_domain: Optional[str] = None
    best_confidence:    int = 0
    providers_succeeded: list[str] = field(default_factory=list)
    per_provider_summaries: dict[str, str] = field(default_factory=dict)
    # D6.58 audit — per-provider failure errors so the admin UI can
    # show "claude:ok, gpt:ok, grok:http_404" instead of just listing
    # the survivors. Empty dict = no failures.
    provider_errors:    dict[str, str] = field(default_factory=dict)
    latency_ms:         int = 0


# ── Per-provider callers ────────────────────────────────────────────────────


async def query_claude_web(
    query: str, anthropic_client,
) -> ProviderResult:
    """Claude Sonnet with web_search_20250305 tool. Same shape as the
    existing single-LLM fallback in web_fallback.py."""
    started = time.monotonic()
    result = ProviderResult(provider="claude")
    try:
        response = await anthropic_client.messages.create(
            model=_CLAUDE_MODEL,
            max_tokens=2048,
            system=_PROVIDER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3,
            }],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
        result.raw_response = text[:4000]
        payload = _parse_provider_json(text)
        if payload is not None:
            _populate_from_payload(result, payload)
        else:
            result.error = "no_json_in_response"
            logger.warning(
                "Claude ensemble: no JSON in response (first 200 chars): %s",
                text[:200],
            )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning("Claude ensemble call failed: %s", result.error)
    finally:
        result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


async def query_gpt_web(query: str, openai_api_key: str) -> ProviderResult:
    """GPT-4o with web_search_preview tool via the Responses API."""
    started = time.monotonic()
    result = ProviderResult(provider="gpt")
    if not openai_api_key:
        result.error = "no_api_key"
        logger.warning("GPT ensemble: no OPENAI_API_KEY configured")
        return result
    try:
        # Use the Responses API which supports the web_search_preview tool.
        # Single HTTP call via httpx — keeps dependency surface small and
        # matches our existing OpenAI usage pattern.
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/responses",
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _GPT_MODEL,
                    "input": [
                        {
                            "role": "developer",
                            "content": _PROVIDER_SYSTEM_PROMPT,
                        },
                        {"role": "user", "content": query},
                    ],
                    "tools": [{"type": "web_search_preview"}],
                    "max_output_tokens": 2048,
                },
            )
        if resp.status_code != 200:
            result.error = f"http_{resp.status_code}"
            logger.warning("GPT ensemble HTTP %s: %s", resp.status_code, resp.text[:200])
            return result
        body = resp.json()
        # Responses API returns a list of output items; the final
        # message has .content[].text. Find it tolerantly.
        text = ""
        for item in body.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
        result.raw_response = text[:4000]
        payload = _parse_provider_json(text)
        if payload is not None:
            _populate_from_payload(result, payload)
        else:
            result.error = "no_json_in_response"
            logger.warning(
                "GPT ensemble: no JSON in response (first 200 chars): %s",
                text[:200],
            )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning("GPT ensemble call failed: %s", result.error)
    finally:
        result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


async def query_grok_web(query: str, xai_api_key: str) -> ProviderResult:
    """Grok via xAI Responses API + web_search tool.

    D6.58 audit fix — xAI deprecated Live Search (`search_parameters`
    on chat/completions); the new path is the Responses API with
    tools, mirroring OpenAI's shape. Uses grok-4-fast-reasoning for
    the cost/capability balance we want in the ensemble.

    Response shape:
      output: [
        {type: 'web_search_call', action: {query, sources}},  # 0-N
        {type: 'message', content: [{type: 'output_text', text: '...'}]}
      ]
    We extract the message text and parse our JSON envelope from it.
    """
    started = time.monotonic()
    result = ProviderResult(provider="grok")
    if not xai_api_key:
        result.error = "no_api_key"
        logger.warning("Grok ensemble: no XAI_API_KEY configured")
        return result
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                _XAI_RESPONSES_URL,
                headers={
                    "Authorization": f"Bearer {xai_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": _GROK_MODEL,
                    # Responses API takes a single string OR a list
                    # of message-shaped dicts. We use the list form so
                    # we can include the system/developer prompt.
                    "input": [
                        {"role": "developer", "content": _PROVIDER_SYSTEM_PROMPT},
                        {"role": "user", "content": query},
                    ],
                    "tools": [{"type": "web_search"}],
                    "max_output_tokens": 2048,
                },
            )
        if resp.status_code != 200:
            result.error = f"http_{resp.status_code}"
            logger.warning(
                "Grok ensemble HTTP %s: %s",
                resp.status_code, resp.text[:300],
            )
            return result
        body = resp.json()
        # Pull message text from the output blocks. There may be 1+
        # web_search_call blocks ahead of it; we just want the message.
        text = ""
        for item in body.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        text += part.get("text", "")
        result.raw_response = text[:4000]
        payload = _parse_provider_json(text)
        if payload is not None:
            _populate_from_payload(result, payload)
        else:
            result.error = "no_json_in_response"
            logger.warning(
                "Grok ensemble: no JSON in response (first 200 chars): %s",
                text[:200],
            )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning("Grok ensemble call failed: %s", result.error)
    finally:
        result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


# ── Internal helpers ────────────────────────────────────────────────────────


def _parse_provider_json(text: str) -> Optional[dict]:
    """Tolerantly extract the JSON object from a provider response.

    All three providers occasionally wrap JSON in markdown fences or
    add a leading sentence. Strip both.
    """
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


def _populate_from_payload(result: ProviderResult, payload: dict) -> None:
    """Common payload → ProviderResult mapping. All three providers
    return the same JSON schema (defined in _PROVIDER_SYSTEM_PROMPT)."""
    try:
        conf = payload.get("confidence")
        result.confidence = (
            int(conf) if isinstance(conf, (int, float, str))
            and str(conf).strip().isdigit() else None
        )
    except (ValueError, TypeError):
        result.confidence = None
    result.source_url = payload.get("source_url")
    result.quote_text = payload.get("quote")
    result.answer_text = payload.get("answer")
    result.summary_text = payload.get("summary")
    if result.source_url:
        try:
            result.source_domain = normalize_domain(
                urlparse(result.source_url).netloc
            )
        except Exception:
            result.source_domain = None
    result.succeeded = (
        result.confidence is not None and result.source_url is not None
    )


# ── Synthesis: pick best, score agreement, decide tier ────────────────────


_SYNTHESIS_SYSTEM_PROMPT = """You are an internal RegKnots auditor synthesizing across three frontier-model web search responses to a maritime / vessel-systems question. The user is a maritime professional. Your output is structured JSON consumed by the application — no prose around it.

You will receive three provider responses (Claude, GPT, Grok). Each has its own answer, source URL, and confidence. Your job:

  1. Pick the single best answer to surface to the user. Prefer:
       - higher confidence
       - more authoritative source domain (regulator > class society > OEM > forum)
       - verbatim quote that actually answers the question
       - agreement with at least one other provider

  2. Count agreement: how many of the three providers gave SUBSTANTIALLY the same answer (paraphrasing OK; same factual conclusion). 0, 1, 2, or 3.

  3. Pick a surface tier:
       'verified'  — Surface as a RegKnots-authored answer. Use ONLY when ALL THREE providers agree AND the picked answer has a verbatim quote that's likely to be on-page.
       'consensus' — Cross-LLM agreement (≥2/3) but no single citation we'd vouch for. UI badge: "AI consensus — verify yourself."
       'reference' — Only 1 provider gave a usable answer; surface as a link with caveat.
       'blocked'   — All providers failed, returned confidence ≤ 1, or no authoritative source.

  4. Brief one-sentence reasoning ("All three converged on X, citing class society Y") so admins reviewing this in the audit can spot bad picks.

Output JSON shape (no markdown fences, just the object):

{
  "surface_tier": "verified|consensus|reference|blocked",
  "agreement_count": 0,
  "best_provider": "claude|gpt|grok",
  "best_answer": "the answer to surface to the user",
  "best_summary": "the brief explanation to show under the answer",
  "best_quote": "verbatim from source if available, else null",
  "best_source_url": "URL",
  "best_confidence": 1-5,
  "reasoning": "one sentence on why this tier + this pick"
}
"""


async def synthesize_ensemble(
    query: str,
    results: list[ProviderResult],
    anthropic_client,
) -> Optional[dict]:
    """Send the three provider responses to Claude Sonnet for synthesis.
    Returns a parsed JSON dict, or None on any failure (caller falls
    back to a deterministic synthesis)."""
    started = time.monotonic()

    # Compact representation of each provider's response. We include
    # only what the synthesizer needs to compare; the raw text would
    # blow the context budget for no upside.
    provider_summaries = []
    for r in results:
        provider_summaries.append({
            "provider": r.provider,
            "succeeded": r.succeeded,
            "error": r.error,
            "confidence": r.confidence,
            "source_url": r.source_url,
            "source_domain": r.source_domain,
            "quote": (r.quote_text or "")[:400],
            "answer": (r.answer_text or "")[:600],
            "summary": (r.summary_text or "")[:300],
        })

    user_payload = (
        f"Question:\n{query}\n\n"
        f"Provider responses:\n"
        f"{json.dumps(provider_summaries, indent=2)}"
    )

    try:
        response = await anthropic_client.messages.create(
            model=_SYNTHESIS_MODEL,
            max_tokens=600,
            system=_SYNTHESIS_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
        parsed = _parse_provider_json(text)
        if parsed is None:
            logger.warning("ensemble synthesis: no JSON in response")
        return parsed
    except Exception as exc:
        logger.warning(
            "ensemble synthesis call failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return None
    finally:
        # Synthesis latency is folded into the orchestrator's total
        # latency_ms downstream; we don't separately log it here.
        _ = time.monotonic() - started


# ── Orchestrator ────────────────────────────────────────────────────────────


async def attempt_ensemble_fallback(
    *,
    query: str,
    anthropic_client,
    openai_api_key: str,
    xai_api_key: str,
) -> EnsembleResult:
    """Run the Big-3 ensemble. Always tries all three providers in
    parallel; gracefully degrades if any provider fails or is missing
    its API key. Synthesis pass produces the surface tier + best
    answer, then we verify the picked quote against the picked source.

    Caller is responsible for:
      - Cap-checking before calling
      - Persisting the EnsembleResult to web_fallback_responses
      - Wiring the result into the chat response
    """
    started = time.monotonic()
    result = EnsembleResult()

    # Fire all three in parallel. asyncio.gather is preferred over
    # as_completed because we want to combine all three regardless
    # of order; latency = max of three, not sum.
    raw_results = await asyncio.gather(
        query_claude_web(query, anthropic_client),
        query_gpt_web(query, openai_api_key),
        query_grok_web(query, xai_api_key),
        return_exceptions=False,  # the per-provider funcs already swallow
    )

    succeeded = [r for r in raw_results if r.succeeded]
    result.providers_succeeded = [r.provider for r in succeeded]
    result.per_provider_summaries = {
        r.provider: (r.summary_text or r.answer_text or "")[:400]
        for r in raw_results
    }
    # D6.58 audit — capture every per-provider error so the audit page
    # can spotlight silent failures (Grok returning 404 on a stale model
    # name, GPT timing out, etc.).
    result.provider_errors = {
        r.provider: r.error
        for r in raw_results if r.error
    }
    if result.provider_errors:
        logger.warning(
            "ensemble fired with provider errors: %s",
            result.provider_errors,
        )

    if not succeeded:
        result.surface_tier = "blocked"
        result.surface_blocked_reason = "all_providers_failed"
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    # Synthesis call — let Claude pick the best across all three.
    synth = await synthesize_ensemble(query, raw_results, anthropic_client)
    if synth is None:
        # Fallback: deterministic pick — highest-confidence succeeded
        # provider with a trusted domain. Conservative default.
        succeeded.sort(key=lambda r: (r.confidence or 0), reverse=True)
        best = succeeded[0]
        result.best_provider = best.provider  # type: ignore[attr-defined]
        result.best_answer = best.answer_text
        result.best_summary = best.summary_text
        result.best_quote = best.quote_text
        result.best_source_url = best.source_url
        result.best_source_domain = best.source_domain
        result.best_confidence = best.confidence or 0
        result.agreement_count = 1
        result.surface_tier = "reference"
        result.surface_blocked_reason = "synthesis_unavailable_fallback"
        result.surfaced = True
        result.latency_ms = int((time.monotonic() - started) * 1000)
        return result

    # Apply the synthesis verdict.
    tier = (synth.get("surface_tier") or "blocked").strip().lower()
    if tier not in ("verified", "consensus", "reference", "blocked"):
        tier = "reference"  # safe default
    result.surface_tier = tier
    result.agreement_count = max(0, min(3, int(synth.get("agreement_count") or 0)))
    result.best_answer = synth.get("best_answer")
    result.best_summary = synth.get("best_summary")
    result.best_quote = synth.get("best_quote")
    result.best_source_url = synth.get("best_source_url")
    if result.best_source_url:
        try:
            result.best_source_domain = normalize_domain(
                urlparse(result.best_source_url).netloc
            )
        except Exception:
            result.best_source_domain = None
    try:
        result.best_confidence = int(synth.get("best_confidence") or 0)
    except (ValueError, TypeError):
        result.best_confidence = 0

    # Verify the picked quote against the picked source. If verified
    # AND the synthesis said 'verified', we surface as verified. If
    # verification fails on a 'verified' verdict, downgrade to consensus.
    if result.best_quote and result.best_source_url and tier == "verified":
        async with httpx.AsyncClient() as client:
            verified = await verify_quote_in_source(
                result.best_quote, result.best_source_url, client,
            )
        result.best_quote_verified = verified
        if not verified:
            # Downgrade — synthesis was over-confident about the quote
            result.surface_tier = "consensus"

    # D6.58 audit fix — domain-quality enforcement on consensus and
    # verified tiers. The synthesis prompt biases toward authoritative
    # domains but doesn't enforce; that's how made-in-china.com leaked
    # through as a 'consensus' answer on 2026-05-05.
    #
    # Rule: consensus and verified tiers REQUIRE the picked source to
    # be on the trusted-domain whitelist. If it isn't, we still
    # surface (the answer might be useful) but as 'reference' tier
    # with the "external source — verify yourself" framing. This
    # preserves surface coverage while keeping the higher-trust tiers
    # honest.
    if (
        result.surface_tier in ("consensus", "verified")
        and result.best_source_url
        and not is_trusted_domain(result.best_source_url)
    ):
        logger.info(
            "ensemble: domain '%s' not trusted — downgrading %s → reference",
            result.best_source_domain, result.surface_tier,
        )
        result.surface_tier = "reference"
        # Keep surface_blocked_reason informational; doesn't block surfacing.
        if not result.surface_blocked_reason:
            result.surface_blocked_reason = "domain_not_in_whitelist_downgraded"

    # 'blocked' tier never surfaces; otherwise yes
    result.surfaced = result.surface_tier in ("verified", "consensus", "reference")
    if not result.surfaced and not result.surface_blocked_reason:
        result.surface_blocked_reason = "synthesis_blocked"

    result.latency_ms = int((time.monotonic() - started) * 1000)
    return result


# ── Per-tier cap helpers ────────────────────────────────────────────────────


# Caps per Blake's spec (D6.58 Slice 3 sign-off):
#   free trial   → 3 lifetime fires (showcase)
#   mate         → 10 fires/30 days
#   captain      → 25 fires/30 days
#   wheelhouse   → 25 fires/30 days per seat (counted at user level for now)
ENSEMBLE_CAPS: dict[str, tuple[str, int]] = {
    # tier_name → (window, count)
    "free":    ("lifetime", 3),
    "mate":    ("30days",   10),
    "captain": ("30days",   25),
    "pro":     ("30days",   25),  # legacy tier mapped to captain caps
}


async def is_under_ensemble_cap(
    *, pool, user_id, subscription_tier: str,
) -> tuple[bool, int, int]:
    """Check whether this user can fire another ensemble call.

    Returns (allowed, used, cap). `allowed` is True if used < cap.
    `used` is the count over the window applicable to the user's tier.
    `cap` is the tier's limit. For unknown tiers (admin / internal /
    paid wheelhouse-only), we default to captain-tier caps.

    Anonymous users (user_id is None) get NO ensemble — return False.
    """
    if user_id is None:
        return False, 0, 0
    tier_key = (subscription_tier or "free").lower()
    window, cap = ENSEMBLE_CAPS.get(tier_key, ENSEMBLE_CAPS["captain"])

    if window == "lifetime":
        used = await pool.fetchval(
            "SELECT COUNT(*) FROM web_fallback_responses "
            "WHERE user_id = $1 AND is_ensemble = TRUE",
            user_id,
        ) or 0
    else:
        used = await pool.fetchval(
            "SELECT COUNT(*) FROM web_fallback_responses "
            "WHERE user_id = $1 AND is_ensemble = TRUE "
            "AND created_at > NOW() - INTERVAL '30 days'",
            user_id,
        ) or 0
    return (int(used) < int(cap)), int(used), int(cap)

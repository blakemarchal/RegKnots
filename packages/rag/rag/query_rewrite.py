"""Multi-query rewrite for retrieval (Sprint D6.66).

Different from `query_distill` (D6.51, which SHORTENS verbose first
turns). This module EXPANDS every query into 2-3 reformulations so
the retriever has multiple semantic anchors to work from.

Motivating case: 2026-05-06 "Do ring buoy water lights need to be
stenciled" — single-query embedding pulled water-light-specific
chunks but missed 46 CFR 185.604 ("Lifesaving equipment markings"),
the controlling section. A reformulation like "ring buoy marking
requirements" or "vessel name lifesaving equipment" would have
landed 185.604 in the candidate pool.

Cost: one Haiku call per rewrite (~$0.001). Fires on every chat
turn that opts in via `query_rewrite_enabled` config.

Latency: ~400-800ms (Haiku is fast). Runs in parallel with the
original-query embedding so the retrieval pipeline's wall time
grows by max(rewrite, embedding) rather than rewrite + embedding.

Output discipline:
  - Reformulations preserve the user's intent. We're widening the
    search net, not changing what they asked.
  - Each reformulation uses different vocabulary / framing so the
    union of embedding vectors covers more of the corpus surface.
  - We DO NOT rewrite the question shown to the generation model.
    The user's actual query goes into the prompt verbatim — only
    retrieval input is reformulated.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# Haiku 4.5 — same model used by hedge_judge and hedge_audit. One
# capable, fast, cheap reasoning model for all classification /
# rewrite tasks across the retrieval layer.
_REWRITE_MODEL = "claude-haiku-4-5-20251001"

# Cap output to keep cost bounded. 3 reformulations × ~80 tokens
# each + JSON envelope sits well under 400.
_REWRITE_MAX_TOKENS = 400

# Hard upper bound on the number of reformulations we'll keep.
# Even if the model returns 10, we only retrieve against the first
# 3 to bound the embedding fan-out cost.
_MAX_REFORMULATIONS = 3


_REWRITE_SYSTEM_PROMPT = """You are RegKnots' query reformulator. Given a maritime compliance question from a user, produce 2-3 alternative phrasings of the SAME question that approach the regulatory corpus from different angles.

Why we want this:
  - Users phrase questions in plain mariner vocabulary (life jacket, stencil, drill, log).
  - The corpus uses formal CFR / SOLAS vocabulary (lifesaving appliance, marking, training, logbook).
  - A single embedding rarely bridges the gap on its own. Multiple reformulations widen the search net.

What "reformulation" means here:
  - Same intent. Same answer would be correct. We're not changing the question.
  - Different vocabulary / framing. Aim for variety:
      one reformulation in formal CFR vocabulary,
      one reformulation focused on a specific section type / equipment class,
      one reformulation that surfaces an adjacent regulation that often has the answer.
  - Concise. 5-15 words each. Search-engine-suitable, not conversational.

Output JSON only — no prose, no markdown fences:

{
  "reformulations": [
    "first alternative phrasing",
    "second alternative phrasing",
    "third alternative phrasing (optional)"
  ]
}

If the original question is so narrow / well-formed that no reformulation would help (e.g., "What is 46 CFR 185.604?"), return an empty array. Don't pad.

Example:

  Original: "Do ring buoy water lights need to be stenciled?"
  Output:
  {
    "reformulations": [
      "lifesaving equipment marking requirements ring life buoy",
      "ring buoy stenciled vessel name CFR",
      "personal lifesaving appliances marking rule water light"
    ]
  }
"""


@dataclass
class QueryRewrite:
    """Multi-query rewrite output."""
    original: str
    reformulations: list[str]
    model_used: str = _REWRITE_MODEL
    error: Optional[str] = None


async def rewrite_query(
    query: str,
    anthropic_client,
    max_reformulations: int = _MAX_REFORMULATIONS,
) -> QueryRewrite:
    """Produce 2-3 reformulations of the user's query.

    Failure-safe: any error returns an empty `reformulations` list
    with `error` populated. Caller should always proceed with the
    original query — reformulations are additive, never required.
    """
    if not query or not query.strip():
        return QueryRewrite(original=query, reformulations=[])

    try:
        response = await anthropic_client.messages.create(
            model=_REWRITE_MODEL,
            max_tokens=_REWRITE_MAX_TOKENS,
            system=_REWRITE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query[:1000]}],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.info("query_rewrite call failed (proceeding without): %s", err)
        return QueryRewrite(original=query, reformulations=[], error=err)

    parsed = _parse_json(text)
    if parsed is None:
        logger.info(
            "query_rewrite: no JSON in response (proceeding with original): %s",
            text[:200],
        )
        return QueryRewrite(
            original=query, reformulations=[], error="no_json_in_response",
        )

    reformulations_raw = parsed.get("reformulations") or []
    if not isinstance(reformulations_raw, list):
        return QueryRewrite(
            original=query, reformulations=[],
            error="reformulations_not_a_list",
        )

    cleaned: list[str] = []
    seen = {query.strip().lower()}
    for r in reformulations_raw[:max_reformulations]:
        if not isinstance(r, str):
            continue
        s = r.strip()
        if not s:
            continue
        # Drop reformulations that are essentially the same as the original.
        # This is rare but happens when the original is already corpus-vocab.
        sl = s.lower()
        if sl in seen:
            continue
        seen.add(sl)
        cleaned.append(s[:240])

    logger.info(
        "query_rewrite: %d reformulations for %r",
        len(cleaned), query[:80],
    )
    return QueryRewrite(original=query, reformulations=cleaned)


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

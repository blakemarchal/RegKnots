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

CRITICAL: maritime industry has rich slang vocabulary that doesn't appear in formal regulations. A senior captain will use industry slang in plain conversation that maps to specific formal terms in the CFR/SOLAS/ISGOTT/OCIMF stack. If the user's query may contain such slang, ALWAYS include the formal regulatory equivalent in at least one reformulation. The slang→formal mapping is what bridges the search gap.

Examples of maritime slang and the formal equivalents to surface in reformulations:

  Original: "Do ring buoy water lights need to be stenciled?"
  Output:
  {
    "reformulations": [
      "lifesaving equipment marking requirements ring life buoy",
      "ring buoy stenciled vessel name CFR",
      "personal lifesaving appliances marking rule water light"
    ]
  }

  Original: "What size fire wire is required"  ← TANKER SLANG
  Output:
  {
    "reformulations": [
      "emergency towing-off pennant size requirements ISGOTT",
      "33 CFR 155.235 emergency towing arrangement oil tanker",
      "IACS UR W18 emergency towing pennant diameter length"
    ]
  }

  Original: "How often do we test the fire main?"
  Output:
  {
    "reformulations": [
      "fire main system testing frequency",
      "fixed fire-fighting water system pressure test interval",
      "SOLAS II-2 fire main inspection schedule"
    ]
  }

  Original: "ullage requirements for cargo loading"  ← TANKER SLANG
  Output:
  {
    "reformulations": [
      "cargo tank empty space minimum on loading",
      "tanker outage requirement loading completion",
      "46 CFR 153.940 cargo tank filling limits"
    ]
  }

  Original: "do we need a gangway watch in port"  ← OPERATIONAL SLANG
  Output:
  {
    "reformulations": [
      "accommodation ladder watch requirements in port",
      "ship security plan watch keeper boarding access",
      "33 CFR 105 vessel security access control"
    ]
  }

  Original: "muster requirements"  ← SAFETY SLANG
  Output:
  {
    "reformulations": [
      "muster station assignment requirements",
      "SOLAS III emergency assembly drills passenger",
      "abandonment station crew assignment 46 CFR 109"
    ]
  }

  Original: "what's in the lazarette"  ← SHIP-STRUCTURE SLANG
  Output:
  {
    "reformulations": [
      "after peak compartment construction requirements",
      "stern compartment subdivision SOLAS II-1",
      "after-peak tank steering gear access"
    ]
  }

  Original: "do oilers need STCW"  ← CREW-RATING SLANG
  Output:
  {
    "reformulations": [
      "QMED oiler endorsement STCW requirements",
      "qualified member engine department training",
      "46 CFR 12.501 engine room rating endorsement"
    ]
  }

  Original: "EPIRB battery replacement"  ← ABBREVIATION
  Output:
  {
    "reformulations": [
      "emergency position-indicating radio beacon battery service",
      "satellite EPIRB Cospas-Sarsat battery replacement interval",
      "47 CFR 80 distress beacon maintenance schedule"
    ]
  }

  Original: "scupper area calculation"  ← DECK-DRAINAGE SLANG
  Output:
  {
    "reformulations": [
      "freeing port area Load Lines Convention",
      "deck drainage opening minimum bulwark requirement",
      "ILLC Reg.24 deck water clearance"
    ]
  }

Note the pattern: every example pulls in (a) the formal regulatory term, (b) a specific CFR/SOLAS/IMO citation when known, and (c) variant phrasings. The user query stays the same; the reformulations widen the lexical net.

Common slang→formal mappings to recognize (not exhaustive — when in doubt, treat any non-CFR term as candidate slang and produce one CFR-vocab reformulation):

- fire wire = emergency towing-off pennant (ETOP) | tanker
- gantline = bosun's chair safety line / manrider | all
- bitt = bollard / mooring fitting | all
- chock = fairlead / panama chock | all
- scotchman = chafe protection / anti-chafe pad | all
- dunnage = cargo securing material / stowage material | all
- tally = manifest count / cargo manifest | all
- ullage = tank empty space / outage | tanker
- cofferdam / void = isolating space | all
- gangway = accommodation ladder / boarding ramp | all
- scupper / freeing port = deck drainage opening | all
- monkey island = compass deck | all
- lazarette = after peak / stern compartment | all
- donkeyman / oiler / wiper = QMED / qualified engine rating | all
- bosun = boatswain / Able Seafarer Deck | all
- lifejacket = lifesaving appliance / personal flotation | all
- mob = man overboard / person overboard | all
- EPIRB = emergency position-indicating radio beacon | all
- SART = search and rescue transponder | all
- DR = dead reckoning position | all
- MMC = Merchant Mariner Credential | US-flag
- COI = Certificate of Inspection | US-flag
- IOPP = International Oil Pollution Prevention Certificate | all
- PSC = Port State Control | all
- ORB = Oil Record Book | all
- hazmat / DG = dangerous goods (49 CFR 172 / IMDG Code) | all
- MSDS = Safety Data Sheet (SDS) | all

Apply the rule with judgment: if the original query is already in formal CFR vocabulary, no slang substitution is needed — just produce variant phrasings of the same formal terms.
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

"""Hedge audit classifier — the mariner-in-the-loop feedback loop.

Sprint D6.58 Slice 2.

When the model hedges (or surfaces only a 'reference' tier web
fallback), we fire a Haiku-class classification call to bucket the
miss and recommend a next step. Results land in the `hedge_audits`
table for admin review.

This is async / fire-and-forget — it must NEVER block or delay the
user-facing chat response. Failures are swallowed; missing audits
are tolerable, but adding latency to every hedged answer is not.

Categories (mutually exclusive, classifier picks the best fit):

  VOCAB         User term doesn't match corpus phrasing
                e.g. "lifejacket" → "lifesaving appliance"
                Recommendation: add to synonyms.py term dict

  INTENT        Query intent doesn't match retrieval target
                e.g. "how often launched?" → equipment-capability
                section instead of training/drills section
                Recommendation: extend intent expansion patterns

  RANKING       Right section was in the candidate pool but ranked
                too low to make the top-K cut
                Recommendation: tune reranker weights or add a
                section-title boost

  COSINE        All top-K candidates were genuinely irrelevant
                Recommendation: investigate query embedding;
                consider corpus expansion if it's a real gap

  CORPUS_GAP    The answer isn't in our corpus at all
                Recommendation: ingest the source identified in
                reasoning (NVIC X, MSC.Y resolution, etc.)

  JURISDICTION  Wrong scope applied (US answer to non-US flag user,
                personal answer to workspace context, etc.)
                Recommendation: tune jurisdiction filter / scope rules

  OTHER         Doesn't fit existing patterns; flag for human
                review by Karynn / admin

The classifier is given:
  - the user's query
  - top-K retrieved sections (source, section_number, section_title,
    similarity)
  - the assistant's hedge text (so the model can see HOW we hedged)
  - vessel/jurisdiction context (so it can spot scope issues)

It returns a JSON object with `classification`, `reasoning`,
`recommendation`. We log the verbatim model output for replay.

Cost: ~$0.001 per classification on Haiku (~500 input tokens, ~200
output tokens). At ~5% hedge rate, ~$0.05/day at current scale.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)


_CLASSIFIER_MODEL = "claude-haiku-4-5-20251001"

_VALID_CLASSIFICATIONS = frozenset({
    "VOCAB", "INTENT", "RANKING", "COSINE",
    "CORPUS_GAP", "JURISDICTION", "OTHER",
})


_CLASSIFIER_SYSTEM_PROMPT = """You are an internal RegKnots auditor classifying why a maritime regulatory chat hedged. Your output is consumed by a feedback loop that tunes retrieval, expands the corpus, and tracks ongoing fixes.

Pick exactly ONE classification from this list:

VOCAB
  The user's vocabulary doesn't match the corpus's formal phrasing.
  Example: user asked about "lifejacket" but the corpus uses "lifesaving appliance".
  Sign: top-K retrieved sections are about adjacent topics that share user-words but not user-meaning.

INTENT
  The user's QUERY INTENT doesn't match what retrieval surfaced.
  Example: "how often does a rescue boat need to be launched" — embedding pulled "rescue boat launching" sections (capability) instead of "training and drills" sections (frequency).
  Sign: retrieved sections are about the right equipment, but answer the wrong question type.

RANKING
  The right answer WAS in the retrieval candidate pool but got pushed below the top-K cut by less-relevant matches.
  Sign: scanning the retrieved chunks reveals one that does answer the question, but it's near the bottom or has low similarity.

COSINE
  Top-K candidates are genuinely irrelevant — the embedding got confused.
  Sign: low similarity scores throughout, retrieved sections feel random.

CORPUS_GAP
  The answer isn't in the corpus at all. We need to ingest a new source.
  Sign: the question is about a real document/regulation we'd recognize but don't have. Specific NVIC, MSC resolution, flag-state notice, etc.

JURISDICTION
  The right answer would be specific to the user's vessel context (flag, route, subchapter) and we surfaced the wrong jurisdiction.
  Sign: question implies a non-US flag or specific subchapter, but retrieved sections are US/generic.

OTHER
  Doesn't fit any of the above. Flag for human review.

Return EXACTLY this JSON object (no prose around it, no markdown fences):

{
  "classification": "ONE_OF_THE_SEVEN",
  "reasoning": "1-3 sentences explaining your pick. Cite specific section numbers from the retrieved list when relevant.",
  "recommendation": "1 sentence with the next step. Examples: 'Add lifejacket→lifesaving appliance to synonyms.py' / 'Ingest NVIC 12-14' / 'Investigate why 46 CFR 199.180 was retrieved at rank 7 instead of top-3'"
}

Be specific in `recommendation`. Don't say "improve retrieval" — say which file to edit, which source to ingest, which term to add. Karynn reads these to decide where to spend her week.
"""


@dataclass
class HedgeAuditOutcome:
    """Structured result of one classification call."""
    classification: str  # one of _VALID_CLASSIFICATIONS
    reasoning: str
    recommendation: str
    model: str
    raw_response: str  # for debugging / replay


def _retrieval_summary(retrieved: list[dict]) -> str:
    """Compact text representation of the top-K for the classifier prompt."""
    if not retrieved:
        return "(no candidates retrieved)"
    lines = []
    for i, c in enumerate(retrieved[:8], start=1):
        sim = c.get("similarity")
        sim_str = f"{sim:.3f}" if isinstance(sim, (int, float)) else "?"
        src = c.get("source") or "?"
        sec = c.get("section_number") or "?"
        title = (c.get("section_title") or "")[:80]
        lines.append(f"  {i}. [{sim_str}] {src} :: {sec} — {title}")
    return "\n".join(lines)


async def classify_hedge(
    *,
    query: str,
    retrieved: list[dict],
    hedge_text: str,
    vessel_profile: Optional[dict],
    anthropic_client,
) -> Optional[HedgeAuditOutcome]:
    """Run the classifier. Returns None on any error — caller swallows."""
    vessel_line = ""
    if vessel_profile:
        flag = vessel_profile.get("flag_state") or "?"
        vtype = vessel_profile.get("vessel_type") or "?"
        sub = vessel_profile.get("subchapter") or "?"
        routes = ", ".join(vessel_profile.get("route_types") or []) or "?"
        vessel_line = (
            f"\nVessel context: flag={flag}, type={vtype}, "
            f"subchapter={sub}, routes={routes}"
        )

    user_payload = (
        f"Query: {query}\n"
        f"{vessel_line}\n\n"
        f"Top retrieved sections (rank, similarity, source, section, title):\n"
        f"{_retrieval_summary(retrieved)}\n\n"
        f"Assistant's hedged response (first 800 chars):\n"
        f"{hedge_text[:800]}\n"
    )

    try:
        response = await anthropic_client.messages.create(
            model=_CLASSIFIER_MODEL,
            max_tokens=400,
            system=_CLASSIFIER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
    except Exception as exc:
        logger.warning(
            "hedge classifier API call failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return None

    text = ""
    try:
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception:
        return None

    parsed = _parse_classifier_json(text)
    if parsed is None:
        return None

    cls = parsed.get("classification")
    if cls not in _VALID_CLASSIFICATIONS:
        logger.info("classifier returned invalid class %r — coercing to OTHER", cls)
        cls = "OTHER"

    return HedgeAuditOutcome(
        classification=cls,
        reasoning=str(parsed.get("reasoning") or "")[:2000],
        recommendation=str(parsed.get("recommendation") or "")[:1000],
        model=_CLASSIFIER_MODEL,
        raw_response=text[:4000],
    )


def _parse_classifier_json(text: str) -> Optional[dict]:
    """Tolerantly extract the JSON object from the model's response.

    Haiku is good but occasionally wraps JSON in markdown fences or adds
    a leading sentence. We strip both.
    """
    if not text:
        return None
    cleaned = text.strip()
    # Strip markdown fences if present
    if cleaned.startswith("```"):
        # ```json ... ``` or ``` ... ```
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Fallback: find the first {...} block
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _json_safe(obj):
    """JSON encoder for retrieved-chunks payload.

    The retrieved chunks coming from the retriever contain UUID and
    datetime fields that json.dumps can't serialize by default. We
    coerce both to str — lossy but safe; the audit table only needs
    these for human inspection, not round-tripping.
    """
    from datetime import date, datetime, time
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, (datetime, date, time)):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


async def persist_hedge_audit(
    *,
    pool,
    conversation_id: Optional[UUID],
    user_id: Optional[UUID],
    query: str,
    retrieved: list[dict],
    web_fallback_id: Optional[str],
    web_surface_tier: Optional[str],
    outcome: HedgeAuditOutcome,
) -> None:
    """Insert the audit row. Best-effort; logs but doesn't raise."""
    try:
        await pool.execute(
            """
            INSERT INTO hedge_audits
              (conversation_id, user_id, query,
               top_retrieved_sections,
               web_fallback_id, web_surface_tier,
               classification, classifier_reasoning, recommendation,
               classifier_model)
            VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7, $8, $9, $10)
            """,
            conversation_id, user_id, query,
            json.dumps(retrieved or [], default=_json_safe),
            UUID(web_fallback_id) if web_fallback_id else None,
            web_surface_tier,
            outcome.classification,
            outcome.reasoning,
            outcome.recommendation,
            outcome.model,
        )
    except Exception as exc:
        logger.warning("hedge_audit persist failed: %s", exc)

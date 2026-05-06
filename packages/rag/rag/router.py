"""
Model complexity router.

Uses Haiku to score query complexity 1-3 and select the appropriate Claude
model. When Haiku returns 0 (off-topic), a Sonnet confirmation pass runs
before the engine refuses — Haiku flakes ~20% on borderline maritime-
adjacent queries (e.g. "military truck fire with UN2734 stowage"), and a
single false-block of a legitimate compliance question is worse for trust
than the ~$0.005 it costs to confirm with Sonnet on the rare off-topic
verdicts. Falls back to score 2 (Sonnet) on any classifier error.
"""

import logging
import re

from anthropic import AsyncAnthropic

from rag.models import RouteDecision
from rag.prompts import CLASSIFIER_PROMPT

logger = logging.getLogger(__name__)

MODEL_MAP: dict[int, str] = {
    # D6.58 prelude — score=0 maps to "" (no model). Engine treats it
    # as a short-circuit signal: skip retrieval, skip fallback, skip
    # ensemble; return the polite off-topic refusal directly. This is
    # the abuse-cost gate.
    0: "",
    1: "claude-haiku-4-5-20251001",
    2: "claude-sonnet-4-6",
    3: "claude-opus-4-7",  # Sprint D4 — Opus 4.6 → 4.7 (better reasoning, 1M ctx)
}

# Sprint D4 — regeneration pass always uses Opus 4.7 regardless of the
# initial routed model. Fires only when the citation verifier catches an
# unverified cite or the initial answer hedged (i.e., bad answer already
# happened). Cheap second chance: costs Opus only on failures, not on
# every call. Engine imports this and passes it to the second-try path.
REGENERATION_MODEL: str = "claude-opus-4-7"

_DEFAULT_SCORE = 2


async def _classify_once(
    query: str, client: AsyncAnthropic, model: str,
) -> int | None:
    """Run a single classification pass with the given model.

    Returns the integer score 0-3, or None if the response was unparseable
    (caller decides whether to retry, escalate, or default).
    """
    response = await client.messages.create(
        model=model,
        max_tokens=10,
        messages=[
            {
                "role": "user",
                "content": f"{CLASSIFIER_PROMPT}\n\nQuestion: {query}",
            }
        ],
    )
    text = response.content[0].text.strip()
    match = re.search(r"[0123]", text)
    if not match:
        return None
    score = int(match.group())
    if score not in (0, 1, 2, 3):
        return None
    return score


async def route_query(query: str, client: AsyncAnthropic) -> RouteDecision:
    """Classify query complexity and return the appropriate model selection.

    Pipeline:
      1. Haiku scores the query 0-3.
      2. If Haiku says 0 (off-topic), a Sonnet second-opinion pass runs
         BEFORE the engine refuses. Only when both Haiku AND Sonnet
         agree on 0 do we honor the off-topic gate. Otherwise we
         override with Sonnet's higher score and let retrieval +
         answer generation proceed normally.
      3. On any classifier error (parse failure, API exception), default
         to score 2 — false-blocking a real maritime question is far
         worse for trust than letting an off-topic query through, where
         we only pay ~$0.005 of false-allow against rare 25/day cap.

    Sprint D6.73 — added the Sonnet confirmation pass after Karynn's
    hazmat fire scenario ("military truck on fire next to generators
    above a tank container with UN2734 and UN1202") was refused on the
    third try while passing on the first two. Probe runs confirmed
    Haiku returns 0 in ~20% of trials on this query (and 100% of
    trials on simpler "military truck fire" variants), making single-
    pass classification an unreliable hard-refusal gate for borderline
    compliance scenarios that touch military/government cargo.
    """
    try:
        primary = await _classify_once(query, client, MODEL_MAP[1])
        if primary is None:
            raise ValueError("primary classifier returned no valid score")
    except Exception as exc:
        logger.warning(f"Router classifier failed ({exc}), defaulting to score 2")
        return RouteDecision(
            score=_DEFAULT_SCORE,
            model=MODEL_MAP[_DEFAULT_SCORE],
            is_off_topic=False,
        )

    # Defense-in-depth: a Haiku off-topic verdict triggers a Sonnet
    # confirmation. The cost (Sonnet only fires on suspected off-topic,
    # ~1 query per week in current volume) is negligible against the
    # cost of false-blocking a real maritime question.
    if primary == 0:
        try:
            confirm = await _classify_once(query, client, MODEL_MAP[2])
            if confirm is None:
                # Sonnet response unparseable — err toward allow, since
                # a hard-refusal needs both passes to agree.
                logger.info(
                    "off_topic gate: Haiku=0, Sonnet unparseable → allowing (default to %d)",
                    _DEFAULT_SCORE,
                )
                return RouteDecision(
                    score=_DEFAULT_SCORE,
                    model=MODEL_MAP[_DEFAULT_SCORE],
                    is_off_topic=False,
                )
            if confirm >= 1:
                logger.info(
                    "off_topic gate: Haiku=0 → Sonnet=%d, overriding to allow "
                    "(query=%r)",
                    confirm, query[:120],
                )
                return RouteDecision(
                    score=confirm,
                    model=MODEL_MAP[confirm],
                    is_off_topic=False,
                )
            # Both classifiers agree: genuinely off-topic.
            logger.info(
                "off_topic gate: 2-of-2 confirmed off-topic (query=%r)",
                query[:120],
            )
        except Exception as exc:
            # Sonnet API failure — err toward allow rather than refuse.
            logger.warning(
                "off_topic Sonnet confirm failed (%s) — defaulting to allow", exc,
            )
            return RouteDecision(
                score=_DEFAULT_SCORE,
                model=MODEL_MAP[_DEFAULT_SCORE],
                is_off_topic=False,
            )

    return RouteDecision(
        score=primary,
        model=MODEL_MAP[primary],
        is_off_topic=(primary == 0),
    )

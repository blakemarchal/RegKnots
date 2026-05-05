"""
Model complexity router.

Uses a single Haiku call to score query complexity 1-3 and select the
appropriate Claude model. Falls back to score 2 (Sonnet) on any error.
"""

import logging

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


async def route_query(query: str, client: AsyncAnthropic) -> RouteDecision:
    """Classify query complexity and return the appropriate model selection.

    D6.58 prelude — now also returns score=0 for off-topic queries, in
    which case the engine short-circuits before any retrieval / web
    fallback / ensemble call. This is the cost-abuse gate.

    Default behavior on classifier failure: assume on-topic (score=2)
    rather than off-topic. False-blocking real maritime questions is
    much worse for users than letting an off-topic query through —
    we'd rather pay $0.001 of false-allow than 0% of false-block.
    """
    try:
        response = await client.messages.create(
            model=MODEL_MAP[1],  # always use Haiku for classification
            max_tokens=10,
            messages=[
                {
                    "role": "user",
                    "content": f"{CLASSIFIER_PROMPT}\n\nQuestion: {query}",
                }
            ],
        )
        text = response.content[0].text.strip()
        # Extract first digit. 0-3 valid; anything else falls through
        # to the default (on-topic, Sonnet).
        match = __import__("re").search(r"[0123]", text)
        if not match:
            raise ValueError(f"no valid score digit in response: {text!r}")
        score = int(match.group())
        if score not in (0, 1, 2, 3):
            raise ValueError(f"score out of range: {score!r}")
    except Exception as exc:
        logger.warning(f"Router classifier failed ({exc}), defaulting to score 2")
        score = _DEFAULT_SCORE

    return RouteDecision(
        score=score,
        model=MODEL_MAP[score],
        is_off_topic=(score == 0),
    )

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
    1: "claude-haiku-4-5-20251001",
    2: "claude-sonnet-4-6",
    3: "claude-opus-4-6",
}

_DEFAULT_SCORE = 2


async def route_query(query: str, client: AsyncAnthropic) -> RouteDecision:
    """Classify query complexity and return the appropriate model selection."""
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
        # Extract first digit in case the model returns explanation text
        match = __import__("re").search(r"[123]", text)
        if not match:
            raise ValueError(f"no valid score digit in response: {text!r}")
        score = int(match.group())
        if score not in (1, 2, 3):
            raise ValueError(f"score out of range: {score!r}")
    except Exception as exc:
        logger.warning(f"Router classifier failed ({exc}), defaulting to score 2")
        score = _DEFAULT_SCORE

    return RouteDecision(score=score, model=MODEL_MAP[score])

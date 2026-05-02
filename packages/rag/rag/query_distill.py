"""
Query distillation — Sprint D6.51.

Maritime users frequently write verbose first-turn queries that include
context the retriever doesn't need ("on a 80,000 GT containership
operating under the US flag, on coastal and international trade
routes…"). Embedding that whole preamble dilutes the signal-to-noise
ratio: the actual question ("can the vessel sail with one lube oil
pump out?") gets buried under generic vessel-class vocabulary.

This module pre-distills the query to its core regulatory question
BEFORE embedding, so the retriever can find the rule that actually
governs the question. The original query is still passed to the
generation model — only the embedding-input is distilled.

Trigger conditions (caller's responsibility):
  - First turn (no conversation history)
  - Query length > 120 characters

We don't distill follow-up turns (their context is already accumulated)
or short queries (no preamble to filter).

Cost / latency:
  - Haiku 4.5: ~$0.001/query, ~400-800ms latency
  - Logged to query_distillations for retrospective tuning

Architectural note: query distillation is fire-and-forget — if Haiku
fails or returns garbage, we fall back to the original query. The
caller never sees a degraded retrieval just because distillation
errored.
"""

import asyncio
import json
import logging
import re
import time
from typing import Optional
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)


# Use the same Haiku 4.5 we already pay for in the routing tier.
DISTILL_MODEL = "claude-haiku-4-5-20251001"
DISTILL_MAX_TOKENS = 200      # distilled query is short; cap output cost
DISTILL_TIMEOUT_S = 10.0      # if distill is slow, fall back fast


# Threshold: queries shorter than this skip distillation entirely.
# Tuned to the observation that ~120 chars is roughly where preamble
# starts to outweigh the actual question. Tunable; collect data first.
LENGTH_THRESHOLD_CHARS = 120


_DISTILL_SYSTEM_PROMPT = """You are a maritime regulatory query rewriter. Your only job is to extract the CORE question from a verbose user query so it can be embedded for vector retrieval over a regulatory corpus.

Rules:
1. Drop preamble that describes the vessel, flag, or trade route — the retriever doesn't need it for embedding (it's used by other parts of the system).
2. Keep technical terms specific to the regulation being asked about (e.g., "lube oil pump", "ballast water management", "bilge separator", "STCW endorsement").
3. Keep regulatory citation hints if mentioned (e.g., "33 CFR 110", "MARPOL Annex VI", "SOLAS II-1").
4. Keep dangerous-cargo names (e.g., "UN 2734", "divinylbenzene") — these are critical retrieval anchors.
5. Keep the question intent verb (sail, log, file, comply, certify, etc.).
6. Aim for 30-100 characters in the rewritten query.
7. NEVER add information not in the original query — only subtract.
8. Output ONLY the rewritten query, no explanation, no quotes, no leading "Question:" label.

Examples:
USER: On a 80,000 gross tonnage containership operating under the US Flag, on coastal and international trade routes, can the vessel sail if one of the main engine lube oil pumps isn't working (doesn't come online)?
DISTILLED: main engine lube oil pump redundancy requirements for departure on a US-flag vessel

USER: I'm working on a Subchapter T small passenger vessel that runs harbor tours and I want to know what the rules are for emergency drill alarm signals
DISTILLED: emergency drill alarm signal requirements for Subchapter T small passenger vessels

USER: hi can you tell me about epirbs on tankers
DISTILLED: EPIRB requirements on tankers"""


async def distill_query(
    query: str,
    anthropic_client,
    pool: Optional[asyncpg.Pool] = None,
    user_id: Optional[UUID] = None,
    conversation_id: Optional[UUID] = None,
) -> Optional[str]:
    """Return a distilled core-question version of `query`, or None on
    failure. Caller falls back to the original query when None.

    Always fire-and-forget on the persistence side — DB errors don't
    block the return value. The Anthropic call has a 10s timeout; on
    timeout we return None to fall back to the original query.
    """
    started = time.monotonic()
    distilled: Optional[str] = None
    error: Optional[str] = None

    try:
        response = await asyncio.wait_for(
            anthropic_client.messages.create(
                model=DISTILL_MODEL,
                max_tokens=DISTILL_MAX_TOKENS,
                system=_DISTILL_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": query}],
            ),
            timeout=DISTILL_TIMEOUT_S,
        )
        # Pull the assistant's text response.
        for block in response.content:
            if getattr(block, "type", None) == "text":
                distilled = block.text.strip()
                break

        if distilled:
            # Sanity checks: distilled must be non-empty, shorter than
            # the original (otherwise distillation didn't help), and
            # contain at least one alphabetic character.
            distilled = _sanitize(distilled)
            if (
                not distilled
                or len(distilled) >= len(query)
                or not re.search(r"[a-z]", distilled, re.IGNORECASE)
            ):
                logger.info(
                    "Distillation rejected by sanity check "
                    "(orig=%dch, distilled=%dch)",
                    len(query), len(distilled or ""),
                )
                distilled = None
                error = "rejected_by_sanity_check"

    except asyncio.TimeoutError:
        logger.warning("Distillation timed out after %.1fs", DISTILL_TIMEOUT_S)
        error = "timeout"
    except Exception as exc:
        logger.warning("Distillation failed: %s: %s",
                       type(exc).__name__, str(exc)[:200])
        error = f"{type(exc).__name__}: {str(exc)[:120]}"

    latency_ms = int((time.monotonic() - started) * 1000)

    # Best-effort log to query_distillations. Never block on DB errors.
    if pool is not None:
        try:
            await pool.execute(
                "INSERT INTO query_distillations "
                "  (user_id, conversation_id, original_query, "
                "   distilled_query, model, latency_ms, error) "
                "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                user_id, conversation_id, query, distilled,
                DISTILL_MODEL, latency_ms, error,
            )
        except Exception as exc:
            logger.warning("query_distillations log failed: %s", exc)

    return distilled


# ── Sanitisation ────────────────────────────────────────────────────────────


_QUOTED_PREFIX_RE = re.compile(r'^\s*["“]\s*')
_QUOTED_SUFFIX_RE = re.compile(r'\s*["”]\s*$')
_LABEL_PREFIX_RE = re.compile(
    r"^\s*(?:DISTILLED|Distilled|Question|Rewritten|Output)[:.]?\s*",
    re.IGNORECASE,
)


def _sanitize(text: str) -> str:
    """Strip common Haiku output quirks: leading 'Distilled:' label,
    surrounding quotes, trailing whitespace."""
    s = text.strip()
    s = _LABEL_PREFIX_RE.sub("", s)
    s = _QUOTED_PREFIX_RE.sub("", s)
    s = _QUOTED_SUFFIX_RE.sub("", s)
    s = s.strip()
    # Take only the first line — Haiku occasionally explains itself.
    s = s.splitlines()[0].strip() if s else s
    return s

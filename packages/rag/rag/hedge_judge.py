"""Real-time Haiku-backed hedge verdict (Sprint D6.60).

The regex-based `detect_hedge` (packages/rag/rag/hedge.py) catches
anything the model phrased as a corpus-miss admission. But many of
those matches are precision callouts on otherwise-complete answers —
e.g. an 8-citation answer that adds "btw the procurement-grade approval
sub-categories aren't in my context for this query." Firing the
$0.05+ Big-3 ensemble fallback on those is wasteful spend AND erodes
trust in the yellow card by burying it under redundant content.

This judge runs Haiku ONLY when the regex matched. It receives the
question, the assistant's full answer, and the actual retrieved chunk
text (capped per-chunk + total) and returns one of four verdicts:

  complete_miss      → fire fallback w/ original query (today's behavior)
  partial_miss       → fire fallback w/ judge.missing_topic as the query
  precision_callout  → no fallback (model gave a complete answer + meta-callout)
  false_hedge        → no fallback (regex matched idiomatic usage)

Cost: ~$0.004 per call at full chunk text. Frequency: only when regex
matched (~10-15/day currently). Total: ~$0.06/day.

Latency: 600-900ms. Sits on the fallback path, which is already 3-8s,
so it's invisible to user perception of main-answer arrival.

The judge sees the same evidence the assistant saw (full chunk text,
not just metadata), so it can ground-truth the model's hedge claim
against retrieved content rather than just reading the model's self-
narrative.
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# Haiku 4.5 — same model used by the offline hedge_audit classifier.
# Pinned so a sudden upstream rename doesn't break real-time decisions.
_JUDGE_MODEL = "claude-haiku-4-5-20251001"


# Caps on what we send to the judge. These dominate the cost/latency
# bill for this call. Tune carefully.
DEFAULT_PER_CHUNK_CHARS = 2000   # truncate any single chunk past this
DEFAULT_TOTAL_CHUNK_CHARS = 16_000  # hard ceiling across all chunks
DEFAULT_ANSWER_CHARS = 4000       # the assistant's hedged response


VALID_VERDICTS = ("complete_miss", "partial_miss", "precision_callout", "false_hedge")


@dataclass
class HedgeVerdict:
    """Output of the judge. The four-bucket verdict + supporting fields."""
    verdict: str
    reasoning: str = ""
    missing_topic: Optional[str] = None
    chunks_truncated: bool = False
    raw_response: str = ""
    error: Optional[str] = None
    latency_ms: int = 0


_JUDGE_SYSTEM_PROMPT = """You are an internal RegKnots auditor. The application's regex-based hedge detector matched a phrase in the assistant's response (e.g. "not in my context", "I don't have specific..."), so the system is asking you to decide whether this is a true corpus miss or a false positive.

Your output drives a real-time decision about whether to fire an expensive Big-3 web search ensemble. Be precise.

You will receive:
  - The user's question
  - The assistant's full hedged response
  - The retrieved regulatory chunks the assistant actually had as context (with section_number, section_title, and chunk text)

Classify into ONE of four buckets:

1. complete_miss
   The answer fails to substantively address the question. The assistant either had nothing on-topic in its context or had only tangentially-related material and admitted as much.
   Example: User asks "What are the Class A liferaft maintenance intervals?" Model responds "I don't have specific maintenance interval requirements for Class A liferafts in my context."
   → Fire fallback on the original question.

2. partial_miss
   The answer addresses the question reasonably AND admits a specific named sub-aspect is missing AND that sub-aspect is something the user would plausibly want.
   Example: User asks "What are immersion suit testing requirements?" Model gives general care/storage rules but admits "specific test pressures and inspection intervals aren't in my retrieved context."
   → Fire fallback, but on the missing sub-aspect (the "missing_topic" field).

3. precision_callout
   The answer fully addresses what was asked AND the hedge is about a tangential, niche, procurement-grade, or out-of-scope detail the user did NOT ask about. The model is being precise, not failing.
   Example: User asks "When can a work vest be substituted for a life preserver?" Model gives the complete substitution rule across every CFR subchapter (citing 8+ sections) and adds "btw the specific approval-subpart citations under 33 CFR 146.20(a) for procurement aren't in my context — consult that section directly if you need approval categories."
   → DO NOT fire fallback. The user got a complete answer.

4. false_hedge
   The matched phrase wasn't actually a hedge. The model used the language idiomatically while making a substantive point.
   Example: Model wrote "this regulation is not directly applicable to passenger vessels" — describing non-applicability as a fact, not admitting a corpus gap.
   → DO NOT fire fallback.

Strict rules:
  - "Substantively addresses" = cites the controlling regulation(s) and gives the actual rule. A list of "consult the source" pointers without an actual answer is NOT substantive.
  - Compare the model's hedge claim against the retrieved chunks. If the model says "X is missing" but X is actually present in a retrieved chunk's text, classify as false_hedge — the model misread its own context.
  - partial_miss requires the missing piece to be a real, nameable topic in 3-12 words. If you can't name it concisely, it's probably precision_callout.
  - precision_callout is NOT "the answer is good enough." The hedge has to be genuinely tangential to the asked question. If the user asked X and the hedge is about X (or a core part of X), that's complete_miss or partial_miss, not precision_callout.

Output JSON only (no prose, no markdown fences):

{
  "verdict": "complete_miss" | "partial_miss" | "precision_callout" | "false_hedge",
  "missing_topic": "string" | null,
  "reasoning": "1-2 sentence explanation of why this verdict, anchored to specific evidence (which chunks, which part of the answer, etc.)"
}

For partial_miss, missing_topic must be a search-engine-suitable phrase capturing the specific sub-aspect missing (e.g. "46 CFR 160.055 work vest approval categories" or "STCW immersion suit test pressure intervals").
For other verdicts, missing_topic must be null.
"""


def _build_chunks_section(
    chunks: list[dict],
    per_chunk_chars: int,
    total_chunk_chars: int,
) -> tuple[str, bool]:
    """Render retrieved chunks into a Markdown-flavored block with
    per-chunk + total caps. Returns (text, truncated_flag).

    truncated_flag is True if ANY chunk got per-chunk-truncated OR the
    total cap kicked us off the tail. Stored on retrieval_misses so we
    can post-hoc audit whether truncation degraded any verdicts.
    """
    parts: list[str] = []
    used_chars = 0
    truncated = False
    for i, chunk in enumerate(chunks):
        section_no = chunk.get("section_number") or "(unknown)"
        title = chunk.get("section_title") or ""
        # Chunk text comes from retrieve.py — field is "full_text" or
        # "text" depending on call path. Tolerantly read.
        text = (
            chunk.get("full_text")
            or chunk.get("text")
            or chunk.get("content")
            or ""
        )
        text = str(text)
        if len(text) > per_chunk_chars:
            text = text[:per_chunk_chars] + " […]"
            truncated = True

        block = (
            f"--- Chunk {i + 1}: {section_no} — {title} ---\n"
            f"{text}\n"
        )
        if used_chars + len(block) > total_chunk_chars:
            # Stop adding chunks; total cap reached.
            truncated = True
            break
        parts.append(block)
        used_chars += len(block)

    if not parts:
        return "(no chunks retrieved)", truncated
    return "\n".join(parts), truncated


async def judge_hedge(
    *,
    question: str,
    answer: str,
    chunks: list[dict],
    citations: list[dict],
    anthropic_client,
    per_chunk_chars: int = DEFAULT_PER_CHUNK_CHARS,
    total_chunk_chars: int = DEFAULT_TOTAL_CHUNK_CHARS,
    answer_chars: int = DEFAULT_ANSWER_CHARS,
) -> HedgeVerdict:
    """Run the Haiku judge. Returns a HedgeVerdict with verdict +
    reasoning + (for partial_miss) missing_topic.

    On any failure (API error, malformed JSON, unknown verdict) returns
    a verdict of 'complete_miss' so the caller falls back to today's
    fire-the-ensemble behavior. Fail-safe: never silently suppress a
    fallback because of a judge failure.

    Args:
      question: the user's original query
      answer: the assistant's full hedged response
      chunks: the list of retrieved chunks the assistant saw. Each
        dict expected to have 'section_number', 'section_title', and
        a chunk-text field ('full_text' / 'text' / 'content').
      citations: list of regs the assistant actually cited (compact
        view: source/section_number/section_title). Helps the judge
        see what the assistant chose to anchor on.
      anthropic_client: AsyncAnthropic client.
      per_chunk_chars / total_chunk_chars / answer_chars: tunable caps.
    """
    started = time.monotonic()
    chunks_block, truncated = _build_chunks_section(
        chunks, per_chunk_chars, total_chunk_chars,
    )
    citations_block = (
        "\n".join(
            f"  - {c.get('section_number') or '?'} — {c.get('section_title') or ''}"
            for c in citations
        )
        if citations else "  (none)"
    )

    truncated_answer = answer or ""
    if len(truncated_answer) > answer_chars:
        truncated_answer = truncated_answer[:answer_chars] + " […]"

    user_payload = (
        f"User's question:\n{question}\n\n"
        f"Assistant's full response (with hedge phrasing):\n"
        f"{truncated_answer}\n\n"
        f"Citations the assistant chose to surface:\n"
        f"{citations_block}\n\n"
        f"Retrieved chunks (the assistant's context):\n"
        f"{chunks_block}"
    )

    try:
        response = await anthropic_client.messages.create(
            model=_JUDGE_MODEL,
            max_tokens=400,
            system=_JUDGE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception as exc:
        err = f"{type(exc).__name__}: {str(exc)[:200]}"
        logger.warning("hedge_judge API call failed (defaulting to complete_miss): %s", err)
        return HedgeVerdict(
            verdict="complete_miss",
            error=err,
            chunks_truncated=truncated,
            latency_ms=int((time.monotonic() - started) * 1000),
        )

    parsed = _parse_judge_json(text)
    latency_ms = int((time.monotonic() - started) * 1000)

    if parsed is None:
        logger.warning(
            "hedge_judge returned no parseable JSON (defaulting to complete_miss): %s",
            text[:200],
        )
        return HedgeVerdict(
            verdict="complete_miss",
            error="no_json_in_response",
            raw_response=text[:1000],
            chunks_truncated=truncated,
            latency_ms=latency_ms,
        )

    verdict_str = (parsed.get("verdict") or "").strip()
    if verdict_str not in VALID_VERDICTS:
        logger.warning(
            "hedge_judge returned unknown verdict %r — defaulting to complete_miss",
            verdict_str,
        )
        return HedgeVerdict(
            verdict="complete_miss",
            error=f"unknown_verdict:{verdict_str}",
            raw_response=text[:1000],
            chunks_truncated=truncated,
            latency_ms=latency_ms,
        )

    missing_topic = parsed.get("missing_topic")
    if missing_topic is not None:
        missing_topic = str(missing_topic).strip() or None
        # partial_miss MUST have a missing_topic; if the model returned
        # a verdict of partial_miss without one, downgrade to complete_miss
        # (we'd have nothing to override the query with anyway).
    if verdict_str == "partial_miss" and not missing_topic:
        logger.info(
            "hedge_judge: partial_miss without missing_topic — downgrading to complete_miss",
        )
        verdict_str = "complete_miss"
        missing_topic = None
    if verdict_str != "partial_miss":
        # Non-partial verdicts ignore missing_topic for cleanliness.
        missing_topic = None

    reasoning = str(parsed.get("reasoning") or "").strip()[:1000]

    logger.info(
        "hedge_judge: verdict=%s missing_topic=%r truncated=%s latency_ms=%d",
        verdict_str, missing_topic, truncated, latency_ms,
    )

    return HedgeVerdict(
        verdict=verdict_str,
        reasoning=reasoning,
        missing_topic=missing_topic,
        chunks_truncated=truncated,
        raw_response=text[:1000],
        error=None,
        latency_ms=latency_ms,
    )


def _parse_judge_json(text: str) -> Optional[dict]:
    """Tolerantly extract the JSON object from Haiku's response.
    Mirrors the parser in ensemble_fallback.py — strips markdown
    fences and tolerates a leading sentence."""
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

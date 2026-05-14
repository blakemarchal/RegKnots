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

# Sprint D6.92 — two invocation paths exposed as a typed parameter so the
# judge can be told which decision rubric to apply. Both paths share the
# same 4-verdict output schema, but the inputs differ:
#   regex_triggered: the regex matched a hedge phrase in the response.
#                    The judge classifies the hedge (real vs false).
#   precautionary:   the response was cited + confident; no regex hit.
#                    The judge looks for an ADMITTED unaddressed
#                    sub-aspect; defaults toward precision_callout
#                    when no gap is named in the response text.
VALID_MODES = ("regex_triggered", "precautionary")


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


# Sprint D6.92 — system prompt restructured to split the two invocation
# paths into separate decision rubrics.
#
# Pre-D6.92 the prompt assumed every response was "hedged" (line 84 of
# the old prompt said "Assistant's full hedged response") and the
# verdict examples all centered on response text admitting a corpus
# gap. That framing biased the judge toward finding a hedge in the
# precautionary path (D6.86) where the response is cited + confident
# and has no hedge phrase. Three documented misfires (Karynn ETA
# 2026-05-11, Karynn fire-ext 2026-05-11, Kenan fire-doors 2026-05-13)
# all got rated `complete_miss` despite 5+ verified citations.
#
# The new prompt makes both paths explicit, gives separate examples,
# and adds a clear "default to precision_callout for confident cited
# answers in MODE B" instruction. It also explicitly removes the
# citation-grounding signal — that's a different layer's job
# (citation oracle) and was leaking into the judge's decision.
_JUDGE_SYSTEM_PROMPT = """You are an internal RegKnots auditor. You receive one of two invocation modes:

MODE A — Regex-triggered review
  A regex detector matched a hedge-like phrase in the response (e.g.
  "not in my context", "I don't have specific...", "context does not
  address..."). Your job: decide whether that matched phrase represents
  a real corpus miss, a tangential precision callout, or a false
  positive. The downstream system uses your verdict to decide whether
  to fire an expensive web-search fallback.

MODE B — Precautionary review of a cited answer
  The response is confident, structured, and cites at least one
  verified regulation. The regex did NOT match — there is NO obvious
  hedge phrase. Your job: decide whether the response *itself* names
  an unaddressed sub-aspect, OR fully addresses the question.

  In MODE B, default to PRECISION_CALLOUT (or FALSE_HEDGE) for any
  confident, structured, cited answer. Only downgrade to PARTIAL_MISS
  when the response text *names* a specific gap. Only downgrade to
  COMPLETE_MISS when the response explicitly admits it can't answer
  the core question — which is rare in MODE B by construction.

IMPORTANT — what this judge is NOT:
  - This judge does NOT verify citations against retrieved chunks. A
    separate citation-oracle layer handles that. Do NOT downgrade a
    verdict because a deep sub-paragraph cited in the response
    (e.g. SOLAS Reg.9.4.1.1.5) isn't literally present in the chunk
    text — chunks typically contain the parent regulation, and
    sub-paragraph detail is properly derived from the parent's body.
  - This judge does NOT score answer quality, citation count, or
    formatting. Only whether the answer addresses the question, or
    whether the response names an unaddressed gap.

You receive:
  - The user's question
  - The assistant's full response
  - The list of verified citations the assistant surfaced
  - The retrieved regulatory chunks the assistant had as context

Classify into ONE of four buckets:

1. complete_miss
   The response fails to substantively address the core of the
   question. Triggered when the response text *itself* states it
   doesn't have / can't answer / lacks coverage for the user's
   main ask.

   MODE A example: User asks "Class A liferaft maintenance intervals?"
   Response says "I don't have specific maintenance interval
   requirements for Class A liferafts in my context." → complete_miss.

   MODE B: rarely applies. A cited, confident answer almost never
   warrants complete_miss. If the response cites authorities and
   states the rule, that's precision_callout, not complete_miss —
   even if you suspect the chunks are thin.

2. partial_miss
   The response addresses the question reasonably AND the response
   text itself *names* a specific sub-aspect that is missing AND that
   sub-aspect is something the user would plausibly want.

   The named gap must appear in the response text. If you have to
   *infer* that "something else might also be relevant," that's NOT
   partial_miss — that's either precision_callout or just a complete
   answer. Don't invent gaps the response didn't mention.

   MODE A example: User asks "immersion suit testing requirements?"
   Response gives general care/storage rules but admits "specific test
   pressures and inspection intervals aren't in my retrieved context."
   → partial_miss with missing_topic="immersion suit test pressures".

3. precision_callout
   MODE A: The response fully addresses what was asked AND any hedge
   or "consult directly" pointer is about a tangential, niche,
   procurement-grade, or out-of-scope detail the user did NOT ask
   about. The model is being precise, not failing.

   MODE B: ANY confident, cited, structured response that addresses
   the question is precision_callout by default. This is the typical
   MODE B verdict.

   Example: User asks "When can a work vest be substituted for a life
   preserver?" Response gives the complete substitution rule across
   every CFR subchapter (citing 8+ sections) and adds "btw the
   approval-subpart citations under 33 CFR 146.20(a) aren't in my
   context — consult that section directly if you need approval
   categories." → precision_callout.

4. false_hedge
   MODE A: The matched phrase wasn't actually a hedge. The model used
   the language idiomatically while making a substantive point.
   Example: Response says "this regulation is not directly applicable
   to passenger vessels" — describing non-applicability as a fact,
   not admitting a corpus gap. → false_hedge.

   MODE B: false_hedge is rare here (no regex match to dismiss);
   prefer precision_callout for cited substantive answers.

Strict rules (both modes):
  - "Substantively addresses" = cites at least one controlling
    regulation AND states the actual rule. A list of "consult the
    source" pointers without a rule statement is NOT substantive.
  - partial_miss requires the gap to be NAMED in the response text.
    Cannot infer a gap that wasn't mentioned.
  - precision_callout is NOT "the answer is decent" — it's
    specifically "the answer is complete; any hedge present is about
    an off-topic detail."
  - For MODE B specifically: bias toward precision_callout. The
    decision threshold for downgrading should be high — the response
    must explicitly state its own incompleteness.

Output JSON only (no prose, no markdown fences):

{
  "verdict": "complete_miss" | "partial_miss" | "precision_callout" | "false_hedge",
  "missing_topic": "string" | null,
  "reasoning": "1-2 sentence explanation, anchored to specific evidence: which part of the response named the gap (if any), or why the answer is complete. Cite the response text or chunk number you're anchoring on."
}

For partial_miss, missing_topic must capture the sub-aspect named in
the response (3-12 words, e.g. "46 CFR 160.055 work vest approval
categories" or "STCW immersion suit test pressure intervals").
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
    mode: str = "regex_triggered",
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

    # Sprint D6.92 — payload framing differs by mode. Regex-triggered:
    # tell the judge to evaluate the matched hedge phrase. Precautionary:
    # tell it to look for an admitted gap in a confident cited answer.
    # The mode marker is the first line so it's impossible to miss.
    if mode == "precautionary":
        mode_header = (
            "MODE B — Precautionary review. The regex did NOT match a "
            "hedge phrase; this is a cited, confident response. Default "
            "to precision_callout unless the response text names a gap."
        )
        response_label = "Assistant's full response (cited, no hedge phrase matched)"
    else:
        mode_header = (
            "MODE A — Regex-triggered review. The regex matched a "
            "hedge-like phrase in the response. Decide whether it's a "
            "real corpus miss, a tangential precision callout, or a "
            "false positive."
        )
        response_label = "Assistant's full response (regex matched a hedge phrase)"

    user_payload = (
        f"{mode_header}\n\n"
        f"User's question:\n{question}\n\n"
        f"{response_label}:\n"
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
        "hedge_judge: mode=%s verdict=%s missing_topic=%r truncated=%s latency_ms=%d reasoning=%r",
        mode, verdict_str, missing_topic, truncated, latency_ms, reasoning[:200],
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

"""Sprint D6.84 — Confidence tier router.

Additive layer on top of the existing chat synthesis pipeline. Decides
which of four confidence tiers a finished answer falls into:

  Tier 1 — ✓ Verified
      The corpus path produced a citable answer. judge_verdict in
      {complete_match, partial_match}, OR ≥1 verified citation
      survives the citation_verifier. No tier_router work needed —
      the answer is rendered as today.

  Tier 2 — ⚓ Industry Standard
      The corpus didn't have a direct hit, but the question is settled
      maritime knowledge that virtually all competent mariners would
      answer the same way. We render WITHOUT a CFR/SOLAS citation but
      WITH an anchor footnote ("General maritime engineering knowledge —
      not cited to a specific regulation").

      Gated by:
        (a) industry_standard_classifier(query) → "yes"
        (b) self-consistency check: regenerate the answer at temp=0.3
            and have Haiku compare core claims. If they disagree
            meaningfully, downgrade to Tier 4.

  Tier 3 — 🌐 Relaxed Web
      Corpus empty AND industry-standard classifier said "no" or the
      self-consistency gate failed, BUT web fallback returned a usable
      result. Render with explicit disclaimer + the existing confidence
      score (1-5). High-confidence web (≥4) is also routed here directly,
      AHEAD of Tier 2, because a verifiable USCG.mil page beats unsourced
      industry knowledge.

  Tier 4 — ⚠ Best-effort
      Nothing else triggered. Today's hedged answer with explicit
      uncertainty.

The router is wrapped in try/except at every callsite — any failure
falls through to today's behavior. The 'off' mode skips this code
entirely; 'shadow' runs it in parallel for forensics; 'live' renders
its decisions.

See docs/sprint-audits/full-system-audit-2026-05-08.md for the
strategic motivation (Jordan Dusek dead-zone failure mode).
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

# Haiku 4.5 — same model used by hedge_judge. Pinned so a sudden
# upstream rename doesn't shift tier-routing behavior silently.
_TIER_MODEL = "claude-haiku-4-5-20251001"

# Regen for self-consistency uses the same Haiku model at low temperature.
# Cheaper than re-running Sonnet, and the comparison only cares about
# the core factual claim, which Haiku is competent on.
_REGEN_TEMPERATURE = 0.3
_REGEN_MAX_TOKENS = 600

# Tier labels — match the strings in the migration's check constraint
# and the frontend chip variants. Keep these in sync.
TIER_VERIFIED = "verified"
TIER_INDUSTRY_STANDARD = "industry_standard"
TIER_RELAXED_WEB = "relaxed_web"
TIER_BEST_EFFORT = "best_effort"

VALID_TIERS = (TIER_VERIFIED, TIER_INDUSTRY_STANDARD, TIER_RELAXED_WEB, TIER_BEST_EFFORT)
VALID_LABEL_TO_TIER = {
    TIER_VERIFIED: 1,
    TIER_INDUSTRY_STANDARD: 2,
    TIER_RELAXED_WEB: 3,
    TIER_BEST_EFFORT: 4,
}

# Web-confidence thresholds — kept identical to the existing Layer C
# constants so behavior is preserved when the new layer is mode=live.
_WEB_HIGH_CONFIDENCE = 4   # web ≥4 outranks Tier 2 (verifiable source beats unsourced industry knowledge)
_WEB_MIN_CONFIDENCE = 3    # web 3-4 still acceptable as Tier 3 fallback after Tier 2 fails


@dataclass
class TierDecision:
    """Result of route_tier(). Pure data — engine.py adapts to the
    Pydantic TierMetadata model on the way out."""
    tier: int                            # 1-4
    label: str                           # one of VALID_TIERS
    reason: str = ""
    classifier_verdict: Optional[str] = None
    classifier_reasoning: Optional[str] = None
    self_consistency_pass: Optional[bool] = None
    self_consistency_reasoning: Optional[str] = None
    web_confidence: Optional[int] = None
    # Optional rendered answer override. When set, engine should
    # render this string instead of cleaned_answer. None preserves
    # the upstream answer.
    rendered_answer: Optional[str] = None
    # Forensic fields — saved to shadow log even when not rendered.
    classifier_latency_ms: int = 0
    self_consistency_latency_ms: int = 0
    error: Optional[str] = None


# ════════════════════════════════════════════════════════════════════
# Industry-standard classifier
# ════════════════════════════════════════════════════════════════════

_CLASSIFIER_SYSTEM_PROMPT = """You are a maritime knowledge classifier for RegKnots, a regulatory copilot used by U.S. commercial mariners. Given a user question, decide whether the answer is settled, uncontroversial maritime engineering or seamanship knowledge that virtually all competent mariners would agree on, OR whether it requires a specific regulatory citation, jurisdiction-specific rule, or expertise outside settled industry consensus.

Your output drives a rendering decision. If you say YES, the system will answer without a regulatory citation but with an "industry knowledge" footnote. If you say NO, it will hedge or route to a web fallback. So be careful with YES — a YES means "any competent senior mariner would answer this without consulting a regulation."

Output JSON only:
{
  "verdict": "yes" | "no" | "uncertain",
  "reasoning": "1 sentence anchored to specific characteristics of the question"
}

Output YES if ALL of the following are true:
  - The question is about general maritime engineering, seamanship, or shipboard practice
  - The answer is the same across virtually all flag states, operators, and vessel classes
  - A senior unlimited Master would answer this without hesitation as common knowledge
  - The answer doesn't depend on a specific regulation, model number, or jurisdictional rule
  - The answer is not a number, threshold, interval, or quantity

Output NO if ANY of the following are true:
  - The question asks for a specific regulatory citation, number, threshold, or interval
  - The answer depends on jurisdiction (US-flag vs IMO vs EU vs class society)
  - The question is about a specific vessel type's classification rule or SMS detail
  - The question quotes or paraphrases CFR / SOLAS / STCW / MARPOL / NVIC text
  - Answers might legitimately differ between operators, sectors, or trades
  - The question is about whether a specific procedure is required (regulatory by nature)

Output UNCERTAIN if you genuinely cannot tell or the question is ambiguous.

EXAMPLES (study carefully — these define the boundary):

Q: Should a watertight door gasket be open or closed cell material?
A: {"verdict": "yes", "reasoning": "Closed-cell elastomer for watertight gaskets is settled marine engineering — universal across all sectors."}

Q: How often should a bilge pump be tested?
A: {"verdict": "no", "reasoning": "Testing intervals are regulatory and vary by vessel class, SMS, and flag."}

Q: What is the maximum allowable PCB concentration in shipboard waste oil?
A: {"verdict": "no", "reasoning": "Specific regulatory threshold under MARPOL Annex V / 33 CFR."}

Q: Should a fire main be kept charged or dry while in port?
A: {"verdict": "yes", "reasoning": "Universal practice — fire main stays charged for response time."}

Q: How many fire extinguishers does a small passenger vessel require?
A: {"verdict": "no", "reasoning": "Direct CFR regulatory question (46 CFR Subchapter T quantity rule)."}

Q: Why are ring buoys stenciled with the vessel's name and hailing port?
A: {"verdict": "yes", "reasoning": "Universal stenciling convention rooted in SAR identification practice."}

Q: What's the difference between a green and white signaling column?
A: {"verdict": "yes", "reasoning": "Settled visual signal convention, same across operators."}

Q: Can I use mineral oil in the main engine sump?
A: {"verdict": "no", "reasoning": "Depends on engine make/model and classification society approval."}

Q: Should engine room watchstanders use a strobe light during emergencies?
A: {"verdict": "no", "reasoning": "Regulatory + vessel-SMS-specific (varies by company alarm policy and CFR Subchapter)."}

Q: What is the proper technique for heaving a line?
A: {"verdict": "yes", "reasoning": "Seamanship fundamental, same on every vessel."}

Q: How do I report an oil spill?
A: {"verdict": "no", "reasoning": "Specific regulatory reporting procedure (33 CFR 153 / NRC notification thresholds)."}

Q: Why does a fishing vessel show red over white at night?
A: {"verdict": "yes", "reasoning": "COLREGS Rule 26 visual signal — universal navigation knowledge any deck officer carries."}
"""


async def classify_industry_standard(
    *,
    query: str,
    anthropic_client,
) -> tuple[str, str, int]:
    """Classify whether `query` can be answered as settled industry
    knowledge.

    Returns (verdict, reasoning, latency_ms). Verdict is one of:
        "yes" | "no" | "uncertain"

    On any failure (API error, malformed JSON), returns
    ("uncertain", "<error>", latency). The caller treats UNCERTAIN as a
    NO for routing purposes — fail-safe defaults to today's hedge
    behavior, never to confident answers.
    """
    started = time.monotonic()
    try:
        response = await anthropic_client.messages.create(
            model=_TIER_MODEL,
            max_tokens=200,
            system=_CLASSIFIER_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Q: {query}"}],
        )
        text = ""
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text += block.text
    except Exception as exc:
        latency = int((time.monotonic() - started) * 1000)
        logger.warning(
            "tier_router classifier API call failed (defaulting to uncertain): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return ("uncertain", f"api_error:{type(exc).__name__}", latency)

    parsed = _parse_json_object(text)
    latency = int((time.monotonic() - started) * 1000)
    if parsed is None:
        logger.warning(
            "tier_router classifier returned no parseable JSON: %s",
            text[:200],
        )
        return ("uncertain", "no_json_in_response", latency)

    verdict = (parsed.get("verdict") or "").strip().lower()
    if verdict not in ("yes", "no", "uncertain"):
        logger.warning(
            "tier_router classifier returned unknown verdict %r — defaulting to uncertain",
            verdict,
        )
        return ("uncertain", f"unknown_verdict:{verdict}", latency)

    reasoning = str(parsed.get("reasoning") or "").strip()[:500]
    logger.info(
        "tier_router classifier: verdict=%s latency_ms=%d query=%r",
        verdict, latency, query[:80],
    )
    return (verdict, reasoning, latency)


# ════════════════════════════════════════════════════════════════════
# Self-consistency gate
# ════════════════════════════════════════════════════════════════════

_REGEN_SYSTEM_PROMPT = """You are RegKnots, a maritime regulatory copilot. Answer the user's question concisely (3-5 sentences max), focusing on the core factual claim. Use general maritime engineering / seamanship knowledge — you do NOT have access to a regulatory corpus on this turn, so do not fabricate citations. Just give your best technical answer.

If the question is genuinely ambiguous or you cannot answer with confidence, respond with: I cannot answer this with confidence."""


_COMPARATOR_SYSTEM_PROMPT = """You are checking whether two short answers to the same maritime question agree on the core factual claim.

You will be shown a question and two answers. Output JSON only:
{
  "verdict": "agree" | "disagree" | "ambiguous",
  "reasoning": "1 sentence explaining the comparison"
}

AGREE — both answers convey the same core factual claim. Wording, ordering, and supporting detail can differ; only the central factual claim matters.

DISAGREE — the answers make conflicting factual claims about the central question (e.g., one says "closed-cell" and the other says "open-cell"; one says "always charged" and the other says "depends").

AMBIGUOUS — at least one answer is non-committal ("I cannot answer this with confidence", "consult a regulation", etc.) so you cannot tell whether they agree.

Be strict. If you are unsure, output AMBIGUOUS. The downstream system treats AMBIGUOUS as "do not promote to industry-standard tier" — same as DISAGREE.

EXAMPLE 1:
Q: Should a watertight door gasket be open or closed cell material?
Answer A: Watertight door gaskets should be closed-cell elastomer. Closed-cell prevents water absorption and maintains compressive set under hydrostatic load.
Answer B: Closed-cell. Open-cell foam absorbs water and loses its seal under pressure.
→ {"verdict": "agree", "reasoning": "Both say closed-cell with the same hydrostatic/absorption rationale."}

EXAMPLE 2:
Q: Should a fire main be kept charged or dry in port?
Answer A: Fire mains stay charged in port for immediate response capability.
Answer B: It depends on the vessel — some operators dry the line during cold weather to prevent freezing.
→ {"verdict": "disagree", "reasoning": "A says always charged, B says it varies by operator/conditions."}

EXAMPLE 3:
Q: What's the maximum bilge water oil content?
Answer A: I cannot answer this with confidence.
Answer B: 15 ppm under MARPOL Annex I.
→ {"verdict": "ambiguous", "reasoning": "A declines to answer."}
"""


async def self_consistency_check(
    *,
    query: str,
    original_answer: str,
    anthropic_client,
) -> tuple[bool, str, int]:
    """Regenerate a brief answer at temp=0.3 and Haiku-compare the two.

    Returns (passed, reasoning, latency_ms). Passed is True only if the
    comparator says AGREE. AMBIGUOUS / DISAGREE both return False.

    On any failure, returns (False, "<error>", latency) — fail-safe
    defaults to "downgrade to next tier", never to "promote anyway."
    """
    started = time.monotonic()
    try:
        regen_resp = await anthropic_client.messages.create(
            model=_TIER_MODEL,
            max_tokens=_REGEN_MAX_TOKENS,
            temperature=_REGEN_TEMPERATURE,
            system=_REGEN_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": query}],
        )
        regen_text = ""
        for block in regen_resp.content:
            if getattr(block, "type", None) == "text":
                regen_text += block.text
        regen_text = regen_text.strip()
        if not regen_text:
            latency = int((time.monotonic() - started) * 1000)
            return (False, "regen_empty", latency)

        comparator_payload = (
            f"Q: {query}\n\n"
            f"Answer A:\n{_truncate(original_answer, 1500)}\n\n"
            f"Answer B:\n{_truncate(regen_text, 1500)}\n"
        )
        cmp_resp = await anthropic_client.messages.create(
            model=_TIER_MODEL,
            max_tokens=200,
            system=_COMPARATOR_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": comparator_payload}],
        )
        cmp_text = ""
        for block in cmp_resp.content:
            if getattr(block, "type", None) == "text":
                cmp_text += block.text
    except Exception as exc:
        latency = int((time.monotonic() - started) * 1000)
        logger.warning(
            "tier_router self_consistency API call failed (defaulting to FAIL): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return (False, f"api_error:{type(exc).__name__}", latency)

    parsed = _parse_json_object(cmp_text)
    latency = int((time.monotonic() - started) * 1000)
    if parsed is None:
        return (False, "no_json_in_comparator_response", latency)

    verdict = (parsed.get("verdict") or "").strip().lower()
    reasoning = str(parsed.get("reasoning") or "").strip()[:500]
    passed = (verdict == "agree")
    logger.info(
        "tier_router self_consistency: verdict=%s passed=%s latency_ms=%d",
        verdict, passed, latency,
    )
    return (passed, reasoning, latency)


# ════════════════════════════════════════════════════════════════════
# Industry-standard answer rendering (for Tier 2)
# ════════════════════════════════════════════════════════════════════

_INDUSTRY_FOOTNOTE_MARKER = "⚓ General maritime engineering knowledge — not cited to a specific regulation."


def render_industry_standard_answer(answer: str) -> str:
    """Append the anchor-icon footnote to a Tier 2 answer.

    The frontend chip already conveys "Industry Standard" — the
    footnote is the inline epistemic disclosure so the user reading
    just the message text still sees the provenance status.

    Idempotent: if the marker is already present, returns input unchanged.
    """
    if not answer:
        return answer
    if _INDUSTRY_FOOTNOTE_MARKER in answer:
        return answer
    answer = answer.rstrip()
    return f"{answer}\n\n---\n*{_INDUSTRY_FOOTNOTE_MARKER}*"


# ════════════════════════════════════════════════════════════════════
# Tier router — the actual decision engine
# ════════════════════════════════════════════════════════════════════

async def route_tier(
    *,
    query: str,
    cleaned_answer: str,
    verified_citations_count: int,
    judge_verdict: Optional[str],
    web_fallback_card,
    anthropic_client,
    enable_industry_standard: bool = True,
) -> TierDecision:
    """Decide which confidence tier this answer falls into.

    Decision tree (order matters):

      1. Tier 1 if verified_citations_count ≥ 1 AND judge_verdict in
         {None, complete_match, partial_match, false_hedge, precision_callout}.
         (judge_verdict is None when no hedge phrase was detected — a
         strong positive signal that the answer is solid.)

      2. Tier 3 if web_fallback_card.confidence ≥ _WEB_HIGH_CONFIDENCE.
         A high-confidence verifiable web source outranks unsourced
         industry knowledge. Render relaxed-web.

      3. Tier 2 if industry-standard classifier says YES AND
         self-consistency check passes. Render with anchor footnote.

      4. Tier 3 if web_fallback_card.confidence ≥ _WEB_MIN_CONFIDENCE.
         Lower-confidence web is the next-best thing.

      5. Tier 4 — best-effort / honest hedge. Render today's behavior.

    Wraps every external call in try/except. On internal exception,
    returns a Tier 4 decision with error captured. The caller decides
    whether to render or fall through.
    """
    # ── Tier 1: verified citation path ─────────────────────────────
    judge_ok = judge_verdict in (None, "false_hedge", "precision_callout")
    if verified_citations_count >= 1 and judge_ok:
        return TierDecision(
            tier=1,
            label=TIER_VERIFIED,
            reason=(
                f"verified_citations={verified_citations_count}, "
                f"judge_verdict={judge_verdict or 'no_hedge'}"
            ),
        )

    # ── Tier 3 (high-confidence web) — outranks Tier 2 ────────────
    if web_fallback_card is not None and web_fallback_card.confidence >= _WEB_HIGH_CONFIDENCE:
        return TierDecision(
            tier=3,
            label=TIER_RELAXED_WEB,
            reason=f"high_confidence_web={web_fallback_card.confidence}",
            web_confidence=web_fallback_card.confidence,
        )

    # ── Tier 2: industry-standard ──────────────────────────────────
    classifier_verdict: Optional[str] = None
    classifier_reasoning = ""
    classifier_latency = 0
    sc_pass: Optional[bool] = None
    sc_reasoning = ""
    sc_latency = 0

    if enable_industry_standard:
        classifier_verdict, classifier_reasoning, classifier_latency = (
            await classify_industry_standard(
                query=query, anthropic_client=anthropic_client,
            )
        )
        if classifier_verdict == "yes":
            sc_pass, sc_reasoning, sc_latency = await self_consistency_check(
                query=query,
                original_answer=cleaned_answer,
                anthropic_client=anthropic_client,
            )
            if sc_pass:
                return TierDecision(
                    tier=2,
                    label=TIER_INDUSTRY_STANDARD,
                    reason=(
                        f"classifier=yes; self_consistency=pass; "
                        f"classifier_reason={classifier_reasoning[:120]}; "
                        f"sc_reason={sc_reasoning[:120]}"
                    ),
                    classifier_verdict=classifier_verdict,
                    classifier_reasoning=classifier_reasoning,
                    self_consistency_pass=True,
                    self_consistency_reasoning=sc_reasoning,
                    classifier_latency_ms=classifier_latency,
                    self_consistency_latency_ms=sc_latency,
                    rendered_answer=render_industry_standard_answer(cleaned_answer),
                )
            # Classifier said yes but self-consistency failed — fall through
            # but preserve forensic data for the shadow log.

    # ── Tier 3 (lower-confidence web) ──────────────────────────────
    if web_fallback_card is not None and web_fallback_card.confidence >= _WEB_MIN_CONFIDENCE:
        return TierDecision(
            tier=3,
            label=TIER_RELAXED_WEB,
            reason=f"web_confidence={web_fallback_card.confidence}",
            web_confidence=web_fallback_card.confidence,
            classifier_verdict=classifier_verdict,
            classifier_reasoning=classifier_reasoning,
            self_consistency_pass=sc_pass,
            self_consistency_reasoning=sc_reasoning,
            classifier_latency_ms=classifier_latency,
            self_consistency_latency_ms=sc_latency,
        )

    # ── Tier 4: best-effort ────────────────────────────────────────
    reason_parts = []
    if verified_citations_count == 0:
        reason_parts.append("no_verified_citations")
    if judge_verdict in ("complete_miss", "partial_miss"):
        reason_parts.append(f"judge={judge_verdict}")
    if classifier_verdict and classifier_verdict != "yes":
        reason_parts.append(f"classifier={classifier_verdict}")
    if classifier_verdict == "yes" and sc_pass is False:
        reason_parts.append("sc_fail")
    if web_fallback_card is None:
        reason_parts.append("no_web_fallback")
    elif web_fallback_card.confidence < _WEB_MIN_CONFIDENCE:
        reason_parts.append(f"web_confidence={web_fallback_card.confidence}_below_floor")

    return TierDecision(
        tier=4,
        label=TIER_BEST_EFFORT,
        reason="; ".join(reason_parts) or "fall_through",
        classifier_verdict=classifier_verdict,
        classifier_reasoning=classifier_reasoning,
        self_consistency_pass=sc_pass,
        self_consistency_reasoning=sc_reasoning,
        classifier_latency_ms=classifier_latency,
        self_consistency_latency_ms=sc_latency,
        web_confidence=web_fallback_card.confidence if web_fallback_card else None,
    )


# ════════════════════════════════════════════════════════════════════
# Helpers
# ════════════════════════════════════════════════════════════════════

def _parse_json_object(text: str) -> Optional[dict]:
    """Tolerantly parse a JSON object out of a Haiku response. Mirrors
    the logic in hedge_judge._parse_judge_json — strips fences, tolerates
    leading prose."""
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


def _truncate(s: str, n: int) -> str:
    if not s:
        return ""
    if len(s) <= n:
        return s
    return s[:n] + " […]"

"""Hedge-phrase detection.

Centralizes the phrase patterns that signal "I didn't find enough in the
retrieved context to answer this cleanly." Used in two places:

  1. packages/rag/rag/engine.py — every chat() response is scanned; a
     match triggers a log to `retrieval_misses` for offline analysis.

  2. scripts/eval_rag_baseline.py — the grader demotes A→A−, A−→B
     when a hedge is detected, so the eval no longer rewards "partial
     retrieval + honest hedge" with an A grade.

Keeping patterns in one place prevents drift between prod detection and
eval grading. If you add/remove a pattern, both callers pick it up
automatically.
"""
from __future__ import annotations

import re

# Patterns are intentionally narrow — we only match phrases that clearly
# indicate the model is acknowledging insufficient retrieved context, not
# routine caveats or "consult the source" reminders.
HEDGE_PATTERNS: list[str] = [
    # "not (included|covered) in ... context"
    r"not included in\s+(?:the\s+)?(?:verified\s+)?context",
    r"not (?:in|part of)\s+(?:my|the)\s+(?:retrieved|verified|knowledge|regulation)",
    r"not fully covered",
    r"aren'?t fully covered",
    r"isn'?t fully covered",
    r"not fully (?:included|available|captured)",

    # Model self-limit phrases
    r"can'?t confirm",
    r"cannot confirm",
    r"didn'?t surface",
    r"don'?t have the specific",
    r"do not have the specific",
    r"don'?t have (?:a )?specific",
    r"do not have (?:a )?specific",

    # "X does not appear in (the|my) [regulation|retrieved|verified] context"
    r"(?:does not|doesn'?t|do not|don'?t)\s+appear in\s+(?:the|my|any)?",
    r"does not appear in\s+(?:the\s+)?(?:regulation|retrieved|verified|knowledge)",

    # "not present in" / "outside the scope" / explicit corpus admissions
    r"not present in\s+(?:the|my|any)",
    r"outside (?:the scope of|the retrieved)",
    # "outside my X" — only hedge if X is a corpus-specific noun.
    # Deliberately excludes "knowledge" because the system-prompt intro
    # boilerplate says "won't guess at requirements outside my knowledge
    # base" in every "Who are you?" response — that's self-description,
    # not a hedge. Real corpus hedges in production use "verified",
    # "retrieved", "regulation", etc. (verified against prod 2026-04-25:
    # 0 legitimate uses of any of these vs 3 boilerplate intros).
    r"outside my\s+(?:verified|retrieved|regulation|regulatory|corpus|context)",
    r"not available in\s+(?:my|the|this)",

    # "context does not/doesn't contain/include/cover/address" — with up
    # to 80 chars allowed between "context" and the verb ("context provided
    # for this query does not contain" style).
    r"(?:context|corpus|knowledge base)\s+[^.]{0,80}(?:does not|doesn'?t)\s+(?:contain|include|cover|address)",
    r"context (?:does not|doesn'?t) (?:contain|include|cover|address)",
    # "cannot cite specifics" / "cannot provide specific" variants
    r"cannot cite specific",
    r"cannot provide specific",
    r"cannot give (?:you )?specific",
    # "none of these (speak to|cover|address)" — admission that retrieved
    # sources don't answer the question
    r"none of these\s+(?:speak to|cover|address|apply)",
    # "retrieved context covers only X" — explicit narrow-scope admission
    r"retrieved context covers only",
    r"retrieved context (?:does not|doesn'?t|only|is limited|contains only)",

    # Specific-section escape phrases
    r"no specific[^.]{0,40}(?:regulation|section|citation|guidance)",
    r"specific (?:details|sections?)[^.]{0,60}aren'?t",
    r"specific (?:details|sections?)[^.]{0,60}(?:not included|not in|not available)",

    # "regulation context I have" / "retrieved context for this query"
    r"(?:regulation|retrieved|verified) context (?:I have|for this|returned)",
]

_HEDGE_RE = re.compile("|".join(HEDGE_PATTERNS), re.IGNORECASE)


def detect_hedge(answer_text: str) -> str | None:
    """Return the first hedge phrase matched in `answer_text`, or None.

    Returns the actual matched substring (truncated to 120 chars) so the
    caller can log what triggered the detection. This is more useful than
    a bool for after-the-fact tuning of the pattern list.
    """
    if not answer_text:
        return None
    match = _HEDGE_RE.search(answer_text)
    if match is None:
        return None
    return match.group(0)[:120]

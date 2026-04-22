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
    r"not included in\s+(?:the\s+)?(?:verified\s+)?context",
    r"not in\s+(?:my|the)\s+(?:retrieved|verified|knowledge)",
    r"not fully covered",
    r"aren'?t fully covered",
    r"isn'?t fully covered",
    r"can'?t confirm",
    r"cannot confirm",
    r"didn'?t surface",
    r"don'?t have the specific",
    r"do not have the specific",
    r"don'?t have (?:a )?specific",
    r"do not have (?:a )?specific",
    r"not fully (?:included|available|captured)",
    r"no specific[^.]{0,40}(?:regulation|section|citation|guidance)",
    r"context (?:does not|doesn'?t) (?:contain|include|cover)",
    r"specific (?:details|sections?)[^.]{0,60}aren'?t",
    r"specific (?:details|sections?)[^.]{0,60}(?:not included|not in|not available)",
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

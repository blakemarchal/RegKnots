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

    # Sprint D6.48 Phase 2 audit — patterns observed in production hedges
    # that the original set didn't catch. Found by Blake's STRETCH DUCK 07
    # manning query review.
    r"(?:cannot|can'?t) fully answer",
    r"could not fully answer",
    r"unable to fully answer",
    # "weren't surfaced in this query's context" — the model has admitted
    # the verified context is missing the controlling regulation.
    # D6.84 hotfix 2026-05-10: include full-form negations. The original
    # contracted-only patterns missed Sonnet's full-form output ("I did
    # not surface a specific requirement..." on Karynn's gasket query),
    # which made hedge_judge return None and silently promoted the
    # answer through the tier router as Tier 1 verified.
    r"(?:were not|weren'?t) surfaced",
    r"(?:was not|wasn'?t) surfaced",
    r"(?:did not|didn'?t) surface",
    # "won't cite from memory" / "I won't guess" — explicit refusal to
    # answer beyond the corpus, which is a hedge by definition.
    r"won'?t (?:cite|guess|speculate)\s+(?:them )?(?:from memory|without)",
    r"i won'?t cite\s+(?:them|those|specific)",
    # "from the verified context provided" — phrase used to bracket the
    # honesty preface ("I can't fully answer X from the verified context
    # provided"). Catches the prefix path.
    r"from\s+the\s+verified\s+context\s+provided",
    # "almost certainly does not apply" / "doesn't directly apply" —
    # model is rejecting a retrieved chunk as off-topic, which means it
    # had nothing on-topic. Strong hedge signal.
    r"almost certainly (?:does not|doesn'?t|don'?t) apply",
    r"not directly applicable",
    # "doesn't map cleanly to" / "doesn't map to" — model rejecting the
    # retrieved set as the wrong scope.
    r"don'?t (?:contain|include) a\s+\w+\s+rule",
    r"doesn'?t map (?:cleanly )?to",
    r"don'?t map (?:cleanly )?to",

    # Sprint D6.48 Phase 2 audit (Blake review #2, 2026-05-02 14:25) —
    # streaming-path queries that hedged with "did not retrieve…":
    #   "I did not retrieve specific information about Paris MOU's 2025…"
    #   "I did not retrieve information about the most recent IMO MEPC…"
    # The pattern is "<negation> retrieve" + "information" or "specific"
    # within a short window. Strong corpus-gap admission either way.
    r"(?:did not|didn'?t|do not|don'?t)\s+retrieve",
    r"(?:was|were|isn'?t|aren'?t)\s+not\s+retrieved",
    r"haven'?t\s+(?:been\s+)?retrieved",
    r"i\s+(?:could not|couldn'?t)\s+find",
    r"i\s+(?:cannot|can'?t)\s+find",
    # "I don't have retrieved context containing X" — observed in
    # no-vessel-context queries (Blake review #2, no-vessel branch).
    r"don'?t have retrieved context",
    r"do not have retrieved context",
    # "no specific information about <X>" / "no information about <X>"
    # — model admitting it has nothing on the topic.
    r"no\s+(?:specific\s+)?information\s+(?:about|on|regarding)",
    # "limited to <older year>" / "as of <date>, my context only covers"
    # — model dating the corpus and admitting newer content is missing.
    r"(?:my|the)\s+(?:retrieved|verified|knowledge)[^.]{0,40}(?:is\s+limited|only\s+covers|extends only)",
    r"limited to\s+(?:the\s+)?\d{4}",
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

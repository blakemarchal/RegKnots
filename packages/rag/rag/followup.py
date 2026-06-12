"""Conversational follow-up detection + retrieval-query composition.

Sprint D6.4 — closes a class of retrieval failures Karynn hit twice
(2026-04-22 lifeboat-flares; 2026-04-23 conversational follow-up to the
same topic). When a user reformulates or pushes back on a prior answer,
their new message embeds toward meta-discussion content rather than
the actual technical topic — and retrieval misses the chunks that
would have surfaced for a clean version of the same question.

Mechanism:

  1. detect_followup(query) — true if the message starts with or
     contains a small set of clarification / pushback phrases. Pattern
     list is intentionally narrow to avoid over-triggering on fresh
     standalone questions.

  2. compose_followup_query(prior_user_message, current_query) — when a
     follow-up fires, build a combined query string that prepends the
     prior user message. Retrieval then runs against the combined
     embedding which carries both the topical context AND the
     pushback's specific intent.

Caller (rag.engine.chat / chat_with_progress) is responsible for
deciding whether to also escalate the synthesis model — see the
follow-up handling block in engine.py.
"""
from __future__ import annotations

import re

# Patterns that strongly signal the user is reformulating or pushing back
# on the prior answer rather than asking a fresh question. Conservative
# by design: the cost of MISSING a follow-up (status quo) is small; the
# cost of FALSELY tagging a fresh question as a follow-up is potentially
# larger because we'd retrieve against the wrong context.
FOLLOWUP_PATTERNS: list[str] = [
    # Pushback that the prior answer was insufficient
    r"^so you can('?| )t",
    r"^so you (don'?t|do not)",
    r"^so you (didn'?t|did not)",
    r"^you (don'?t|do not) (have|know)",
    r"^you (didn'?t|did not) (mention|address|cover|tell)",
    r"^you keep saying",
    r"^you said",
    r"^that'?s not what i (asked|meant)",

    # Direct clarification / reformulation prompts
    r"^but (what|why|how|where|when|who) (about|do|does|is|are)",
    r"^are you sure",
    r"^why not",
    r"^why (didn'?t|did not|don'?t|don't)",
    r"^what about",

    # Explicit search-for-specifics phrasing
    r"^can you (be more specific|give me|tell me)",
    r"^what (is|are) the (specific|exact|actual)",
    r"^how (many|much|often|long)\b.*\bspecifically\b",

    # Reference back to "this" / "that" without setup — strong signal
    # the user is continuing a thread, not starting fresh.
    r"^and (what|why|how)",
    r"^also,",
]

_FOLLOWUP_RE = re.compile(
    "|".join(FOLLOWUP_PATTERNS),
    re.IGNORECASE,
)


def detect_followup(query: str) -> str | None:
    """Return the matched follow-up phrase, or None.

    NARROW pattern signal — drives BOTH the Opus model escalation and
    (via compose_reason) retrieval-query composition. Genuine pushback
    ("you said X", "are you sure") earns the smarter synthesis model.

    Returns the actual matched substring (truncated to 120 chars) so the
    engine can log what triggered the detection — useful for tuning the
    pattern list against real user data over time.
    """
    if not query:
        return None
    cleaned = query.strip()
    if len(cleaned) < 3:
        return None
    match = _FOLLOWUP_RE.search(cleaned)
    if match is None:
        return None
    return match.group(0)[:120]


# Sprint D6.97 audit (2026-06) — a short message mid-thread is almost
# always a clarification or continuation whose embedding lacks the
# thread's topical anchor. Nirmal's 2026-06-04 provisions thread is the
# canonical failure: his clarifications "The question is about USCG best
# before date rule" (47ch) and "I am talking about General provisions
# for daily consumption" (58ch) matched NONE of the FOLLOWUP_PATTERNS,
# so retrieval ran on the bare words with no topical context → a
# complete miss. Pattern-matching can't keep up with the infinite ways a
# user phrases a clarification; message length is the robust signal.
_SHORT_FOLLOWUP_CHARS = 140


def compose_reason(query: str, history_len: int) -> str | None:
    """Return a short reason string when the retrieval query should be
    COMPOSED with the prior user message, else None.

    BROAD signal — drives retrieval-query composition only (cheap: it
    just changes what we embed). Deliberately decoupled from
    detect_followup, which ALSO gates the expensive Opus escalation:
    composition should be generous, model-escalation should not.

    Two triggers, both requiring a non-empty conversation history:
      1. A pushback/clarification PATTERN matched (detect_followup).
      2. The message is SHORT (< _SHORT_FOLLOWUP_CHARS). Short mid-thread
         messages overwhelmingly continue the established topic; the
         prior user message restores the context the short query drops.

    First-turn queries (history_len == 0) never compose — there is no
    prior message and verbose first turns go through query distillation
    instead (see engine.py).
    """
    if history_len <= 0:
        return None
    pattern = detect_followup(query)
    if pattern:
        return f"pattern:{pattern}"
    if len((query or "").strip()) < _SHORT_FOLLOWUP_CHARS:
        return f"short:{len((query or '').strip())}ch"
    return None


def compose_followup_query(
    prior_user_message: str | None,
    current_query: str,
    *,
    prior_max_chars: int = 400,
    current_max_chars: int = 600,
) -> str:
    """Build a combined query string for retrieval.

    Strategy: place the prior user message FIRST so it dominates the
    embedding's topical center, then append the current query. Hard
    char caps so the combined string doesn't blow past embedding-input
    limits or pollute retrieval with irrelevant context.

    If no prior user message is available (first turn, or history was
    purged), returns the current query unchanged — caller has nothing
    to combine with.
    """
    current = (current_query or "").strip()[:current_max_chars]
    if not prior_user_message:
        return current
    prior = prior_user_message.strip()[:prior_max_chars]
    if not prior:
        return current
    return f"{prior}\n\n[Follow-up:] {current}"

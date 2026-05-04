"""Mariner-vocabulary → CFR-vocabulary synonym expansion.

Sprint D6.8 — fixes a class of retrieval misses where the user uses
plain mariner vocabulary ("lifejacket") but the formal CFR section
titles use different terms ("lifesaving appliance"). The corpus has
the answer; trigram + vector retrieval just doesn't bridge the synonym
gap reliably.

Documented case that motivated this: Patrick Cloud / HOS Bayou /
Subchapter L OSV asked "do lifejacket inspections have to be logged
anywhere?" on 2026-04-25. Top-K returned 8 unrelated chunks (49 CFR
match packaging, ELD recording, jackup tow procedures, ballast water,
…). The actually-correct chunk — 46 CFR 133.45 "Tests and inspections
of lifesaving equipment and arrangements" — was in the corpus and
inside the OSV applicability set, but trigram scored it at 0.04 because
"lifejacket" doesn't appear in the section title and "log" matched the
wrong neighborhood (ELD logs, casualty investigation logs).

Design intentionally conservative: we only add entries we have HIGH
confidence about from observed user data. Three entries today:

  1. lifejacket → lifesaving appliance / lifesaving / PFD
  2. log → logbook / official logbook / deck log
  3. MOB → person overboard / man overboard

Adding more entries SHOULD be evidence-driven — see
`memory/project_retrieval_vocab_mismatch.md` for the candidate list.
Don't speculate; let real misses tell us.

Tradeoff vs the alternatives we considered:
  (a) this — synonym expansion at retrieval time. Picked.
  (b) section-title keyword boost — doesn't fix Patrick's case
      ("lifejacket" isn't in any 46 CFR Part 133 section title).
  (c) cheap-model query-rewrite — adds 250ms + per-query cost; deferred
      until (a) demonstrably misses ≥3 distinct vocab patterns.
"""
from __future__ import annotations

# Each key is the user-facing term (lowercase). Values are the additional
# search terms to ALSO trigram-match against the corpus when the key
# appears in the extracted keyword list.
#
# Entries are deliberately one-directional: we expand FROM user vocab
# INTO corpus vocab. The reverse direction isn't needed because the
# corpus terms are already what the corpus contains.
#
# Frequency check (chunks containing each phrase, prod 2026-04-26):
#   lifesaving appliance     155
#   personal flotation        95
#   logbook                  203
#   official logbook         102
#   deck log                   8
#   person overboard          11
#   man overboard             28
#
# Bare "lifesaving" alone matches 583 chunks — too broad, returns
# generic training/equipment-manual content. Stuck with the targeted
# 2-word phrases so candidate pool stays focused on the user's intent.
SYNONYM_DICT: dict[str, tuple[str, ...]] = {
    "lifejacket": ("lifesaving appliance", "personal flotation"),
    "log": ("logbook", "official logbook", "deck log"),
    "mob": ("person overboard", "man overboard"),
    # Sprint D6.24 — added on documented evidence:
    # 2026-04-29 user 2ndmate09 (chat title "Maritime Stability
    # Requirements CFR Compliance Guide") asked "Which cfr has
    # stability requirements" and got "None of the retrieved sources
    # address vessel stability requirements" — but 46 CFR Subchapter S
    # (Subdivision and Stability) contains exactly that, plus AMSA MO 12
    # and the IGC + HSC Codes cover stability extensively.
    # Frequency-checked 2026-04-29:
    #   subdivision and stability  214 chunks  (Subchapter S formal title)
    #   damage stability           208 chunks  (post-casualty stability)
    #   intact stability           125 chunks  (operational loading)
    # Bare "stability" alone matches 1,401 chunks — too broad to add
    # directly as a search term; staying with targeted 2-word phrases
    # keeps the candidate pool focused on the user's intent.
    "stability": ("subdivision and stability", "damage stability", "intact stability"),
}


def expand_keywords(
    keywords: list[str],
) -> tuple[list[str], dict[str, list[str]]]:
    """Append corpus-vocabulary synonyms for any matching extracted keywords.

    Returns:
        (expanded_keywords, synonym_map) where
          - expanded_keywords: original list plus appended synonyms,
            preserving original order, deduped (first occurrence wins).
          - synonym_map: {original_keyword: [synonyms_added]} for the
            keywords that triggered expansion. Empty dict means no
            expansion fired — caller can skip the log line in that case.

    Multi-word synonyms are passed through verbatim. The caller's
    trigram pass treats them as ILIKE substrings, so "lifesaving
    appliance" matches anywhere that exact phrase appears in
    full_text — which is the formal CFR phrasing.
    """
    if not keywords:
        return [], {}

    out: list[str] = []
    seen: set[str] = set()
    synonym_map: dict[str, list[str]] = {}

    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            out.append(kw)
        synonyms = SYNONYM_DICT.get(kw_lower)
        if not synonyms:
            continue
        added: list[str] = []
        for syn in synonyms:
            syn_lower = syn.lower()
            if syn_lower in seen:
                continue
            seen.add(syn_lower)
            out.append(syn)
            added.append(syn)
        if added:
            synonym_map[kw_lower] = added

    return out, synonym_map


def is_synonym(term: str) -> bool:
    """Return True if `term` is a corpus-vocab synonym (i.e., a value in
    SYNONYM_DICT, not a key). Used by the trigram pass to apply a
    relaxed frequency cap — synonyms are by definition slightly broader
    than user vocab, so the standard cap would falsely skip them.
    """
    term_lower = term.lower()
    for synonyms in SYNONYM_DICT.values():
        for syn in synonyms:
            if syn.lower() == term_lower:
                return True
    return False


# ── Sprint D6.56 — intent expansion ───────────────────────────────────────
#
# Term-level synonyms (above) handle the case where the user uses one
# noun and the corpus uses another ("lifejacket" → "lifesaving
# appliance"). They DON'T handle the case where the user's question
# implies a different SECTION than what the literal terms point to.
#
# Brandon's 2026-05-04 query motivated this:
#
#   Q: "How often does a rescue boat need to be launched cfr"
#
# Embedding pulled "rescue boat launched" hard and landed on
# §§108.570 / 133.160 / 199.160 — the LAUNCHING-ARRANGEMENT sections.
# But the answer to "how often" lives in §§199.180 / 109.213 /
# 122.520 / 185.520 / 35.10-1 — the TRAINING-AND-DRILLS sections,
# which are titled with vocabulary the user never used ("training",
# "drills", "musters").
#
# Intent expansion fires when the query carries:
#   1. A FREQUENCY MARKER ("how often", "interval", "schedule",
#      "weekly", "monthly", etc.)
# AND
#   2. An EMERGENCY-EQUIPMENT TERM (lifeboat, rescue boat, fire alarm,
#      lifejacket, immersion suit, etc.)
#
# When both fire, we append the corpus's canonical drill / training
# vocabulary as additional trigram-search terms. Vector embedding is
# unchanged; the new terms just give trigram a chance to surface the
# right sections, which the reranker then promotes.
#
# Same conservative principle as SYNONYM_DICT: only patterns we have
# direct evidence for. Add more as new misses surface.


_FREQUENCY_TOKENS: frozenset[str] = frozenset({
    # Token-level frequency words after stopword removal
    "frequency", "interval", "intervals", "schedule",
    "weekly", "biweekly", "fortnightly",
    "monthly", "annually", "yearly", "quarterly",
    "rotation", "periodic", "periodically",
})

_FREQUENCY_PHRASES: tuple[str, ...] = (
    # Phrase-level markers checked against the raw query (lowercase).
    # Stopword-aware extraction would drop "how" + "often"; we look at
    # the raw text for these.
    "how often", "how frequently", "how regularly",
    "how many times", "how much time between",
    "every how",
)

_EMERGENCY_EQUIPMENT: frozenset[str] = frozenset({
    # Tokens (post-stopword extraction) that signal emergency-context
    # equipment whose corpus answer lives in a drill/training section
    # rather than the equipment-capability section.
    "lifeboat", "lifeboats",
    "rescue",            # paired with "boat" via _EMERGENCY_PHRASES
    "liferaft", "raft", "rafts",
    "immersion", "suit",
    "lifejacket", "pfd",
    "abandon",           # paired with "ship" via _EMERGENCY_PHRASES
    "alarm", "alarms",
    "muster", "musters",
    "emergency",
    "fire",
    "drill", "drills",   # already corpus vocab; harmless to keep
})

_EMERGENCY_PHRASES: tuple[str, ...] = (
    # When these multi-word phrases appear, count as emergency context
    # even if the individual tokens are too generic (e.g. "fire").
    "rescue boat", "abandon ship", "fire alarm", "fire pump",
    "fire detection", "fire drill", "abandon-ship drill",
    "emergency generator", "emergency lighting",
)

# Canonical CFR / SOLAS vocabulary appended when intent fires.
# Multi-word phrases pass through verbatim — trigram treats them as
# ILIKE substrings, matching exact phrases in section text/titles.
_DRILL_INTENT_VOCAB: tuple[str, ...] = (
    "drill",
    "training",
    "musters",
    "operational readiness",
    "inspection",
)


def expand_intent(
    query: str, keywords: list[str],
) -> tuple[list[str], list[str]]:
    """Detect intent patterns and append canonical vocab to keywords.

    Returns:
        (expanded_keywords, intent_added) where
          - expanded_keywords: original list plus any appended canonical
            vocab. Original order preserved; appended terms come last.
          - intent_added: just the appended terms, for the caller to
            pass to _broad_keyword_search as synonym_keywords (so the
            relaxed freq cap applies — these terms are by design
            broader than user vocab, like real synonyms).
    """
    if not keywords:
        return list(keywords), []

    query_lower = query.lower()
    keyword_set = {k.lower() for k in keywords}

    # Frequency signal: token-level OR phrase-level
    has_freq_token = any(k in _FREQUENCY_TOKENS for k in keyword_set)
    has_freq_phrase = any(p in query_lower for p in _FREQUENCY_PHRASES)
    if not (has_freq_token or has_freq_phrase):
        return list(keywords), []

    # Emergency-context signal: token-level OR phrase-level
    has_eq_token = any(k in _EMERGENCY_EQUIPMENT for k in keyword_set)
    has_eq_phrase = any(p in query_lower for p in _EMERGENCY_PHRASES)
    if not (has_eq_token or has_eq_phrase):
        return list(keywords), []

    # Both fired — append the canonical drill/training vocabulary.
    out = list(keywords)
    seen = set(keyword_set)
    added: list[str] = []
    for v in _DRILL_INTENT_VOCAB:
        v_lower = v.lower()
        if v_lower in seen:
            continue
        seen.add(v_lower)
        out.append(v)
        added.append(v)
    return out, added

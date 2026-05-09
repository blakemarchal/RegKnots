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
    # Sprint D6.65 — added on documented evidence:
    # 2026-05-06 user Dusekjordan (Jordan Dusek, M/V Southern Tide,
    # Subchapter T) asked "Do ring buoy water lights need to be
    # stenciled" → retrieval pulled water-light-specific chunks
    # (117.70(d)(1), 180.70(d)(1), 144.01-25, 160.053-5) and missed
    # 46 CFR 185.604 ("Lifesaving equipment markings") which directly
    # answers the question. Web fallback surfaced 185.604 from
    # law.cornell.edu — section was IN our corpus but never retrieved
    # because "stencil" doesn't trigram-match a section titled "markings".
    #
    # Frequency-checked 2026-05-06 (corpus chunk counts):
    #   block capital letters          34   (lifesaving + log-book marking)
    #   clearly legible                31   (marking-clarity language)
    #   marked with the vessel          7   (vessel-name marking — exact)
    #   marked with the name           41   (broader name-marking phrasing)
    #   approval number                broad — skipped
    #   marking / markings           1546 / 606 — too broad to add directly
    #
    # Targeted multi-word phrases above keep the candidate pool focused
    # on lifesaving-equipment marking sections (185.604, 184.604, 117.70,
    # 180.70, 199.70). Bare "marking" stays out — it would flood with
    # navigation aids, OPA-90 markings, ERG placards, etc.
    "stencil":     ("clearly legible", "block capital letters", "marked with the name"),
    "stenciled":   ("clearly legible", "block capital letters", "marked with the name"),
    "stenciling":  ("clearly legible", "block capital letters", "marked with the name"),
}


# ── Maritime industry-jargon glossary (post-2026-05-08 audit) ────────────
#
# The curated SYNONYM_DICT above is conservative — entries land only on
# documented retrieval misses. That works but trails real-world demand
# by one painful incident per term ("user asks X → bad answer ships →
# we add the synonym → next user with the same vocabulary is fine").
#
# 2026-05-08: John Collins asked "what size fire wire is required" on
# his containership profile. The corpus has 33 CFR 155.235 +
# IACS UR W18 + IACS UR A2 — none of which retrieved because the user
# said "fire wire" (tanker industry slang) and the formal term is
# "emergency towing-off pennant." The Haiku rewriter doesn't know this
# slang at the depth a senior captain does; the hedge classifier saw
# the miss and proposed wrong synonyms.
#
# Fix: a separate `maritime_glossary.py` module curated from a wider
# brainstorm. Confidence-tagged so we know which entries are still
# Sonnet-only (1) vs. multi-model + corpus-verified (2/3) vs. Karynn-
# verified (4). This SYNONYM_DICT continues to hold the most-tightly-
# evidence-grounded entries; the glossary holds the broader curated set.
#
# Both feed the same retrieval-time keyword-expansion path. Glossary
# entries override SYNONYM_DICT only if a key collides (which today it
# doesn't — different domains).

from rag.maritime_glossary import synonym_pairs as _glossary_synonym_pairs

_GLOSSARY_DICT: dict[str, tuple[str, ...]] = _glossary_synonym_pairs()


# Merge the curated SYNONYM_DICT (precedence) on top of the glossary.
# Glossary entries fill the long tail; SYNONYM_DICT entries — which
# carry per-entry frequency-checked rationale — stay authoritative
# wherever there's overlap.
SYNONYM_DICT = {**_GLOSSARY_DICT, **SYNONYM_DICT}


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


# ── Equipment-marking intent (Sprint D6.65) ─────────────────────────────
# When a user asks about marking / stenciling / labeling lifesaving or
# safety equipment, the answer typically lives in a section TITLED
# "Lifesaving equipment markings" or "Personal lifesaving appliances" —
# words that don't appear in the user's query. Trigram retrieval misses
# every time. This intent matcher injects the canonical CFR section
# titles + marking phrasing so those sections rank in top-K.
#
# Motivating case: 2026-05-06 Jordan Dusek "Do ring buoy water lights
# need to be stenciled" — retrieval pulled water-light-specific sections
# but missed the controlling 46 CFR 185.604 ("Lifesaving equipment
# markings") and 46 CFR 199.70 ("Personal lifesaving appliances"), both
# of which were in the corpus.

_MARKING_TOKENS: frozenset[str] = frozenset({
    # Verbs / nouns the user types when they mean "marking required by reg"
    "stencil", "stenciled", "stenciling",
    "mark", "marked", "marking", "markings",
    "label", "labeled", "labelled", "labeling", "labelling",
    "lettering",
    "imprint", "imprinted",
    "engrave", "engraved",
    "name",  # "name on the buoy" — paired with equipment via _MARKING_PHRASES
})

_MARKING_PHRASES: tuple[str, ...] = (
    # Multi-word marker phrases checked against the raw query lowercase.
    "vessel name", "vessel's name", "ship name", "ship's name",
    "approval number",
    "block letters", "block capital",
    "stenciled with", "marked with",
)

# Equipment-class tokens (post-stopword extraction) that signal
# lifesaving / safety equipment whose marking rule lives in a marking-
# specific section rather than the equipment-spec section.
_LIFESAVING_EQUIPMENT_TOKENS: frozenset[str] = frozenset({
    "buoy", "buoys",
    "lifebuoy", "lifebuoys",
    "ring",  # "ring buoy", "ring life buoy"
    "lifejacket", "lifejackets", "pfd",
    "preserver", "preservers",
    "vest", "vests",
    "raft", "rafts", "liferaft", "liferafts",
    "lifefloat", "float", "floats",
    "suit", "suits",
    "immersion",
    "lifesaving",
    "appliance", "appliances",
    "lifeline", "lifelines",
    "throwline", "throwlines",
    "waterlight", "waterlights",
})

_LIFESAVING_EQUIPMENT_PHRASES: tuple[str, ...] = (
    # Multi-word equipment phrases.
    "ring buoy", "ring life buoy",
    "life jacket", "life vest", "work vest",
    "life ring", "life float",
    "life raft", "life raft",
    "immersion suit",
    "water light",
    "personal flotation",
)

# Canonical phrasing appended when marking-intent fires. Each is
# narrow enough (frequency-checked 2026-05-06) to not flood the
# candidate pool:
#   lifesaving equipment markings    5 chunks   (185.604, 184.604, etc.)
#   personal lifesaving appliances  12 chunks   (199.70 family)
#   marked with the vessel           7 chunks
#   block capital letters           34 chunks
#   clearly legible                 31 chunks
_MARKING_INTENT_VOCAB: tuple[str, ...] = (
    "lifesaving equipment markings",
    "personal lifesaving appliances",
    "marked with the vessel",
    "block capital letters",
    "clearly legible",
)


def _drill_frequency_intent(
    query_lower: str, keyword_set: set[str],
) -> tuple[str, ...]:
    """Return canonical drill/training vocab if (frequency × emergency-
    equipment) signals both fire. Empty tuple otherwise."""
    has_freq_token = any(k in _FREQUENCY_TOKENS for k in keyword_set)
    has_freq_phrase = any(p in query_lower for p in _FREQUENCY_PHRASES)
    if not (has_freq_token or has_freq_phrase):
        return ()
    has_eq_token = any(k in _EMERGENCY_EQUIPMENT for k in keyword_set)
    has_eq_phrase = any(p in query_lower for p in _EMERGENCY_PHRASES)
    if not (has_eq_token or has_eq_phrase):
        return ()
    return _DRILL_INTENT_VOCAB


def _equipment_marking_intent(
    query_lower: str, keyword_set: set[str],
) -> tuple[str, ...]:
    """Return canonical marking vocab if (marking-verb × lifesaving-
    equipment) signals both fire. Empty tuple otherwise.

    Both signals are required to keep the candidate pool focused. A
    user asking about marking on a chart, on a hatch cover, or on a
    cargo manifest hits the marking signal but not the equipment
    signal — those queries should fall through to the standard
    retrieval path.
    """
    has_mark_token = any(k in _MARKING_TOKENS for k in keyword_set)
    has_mark_phrase = any(p in query_lower for p in _MARKING_PHRASES)
    if not (has_mark_token or has_mark_phrase):
        return ()
    has_eq_token = any(k in _LIFESAVING_EQUIPMENT_TOKENS for k in keyword_set)
    has_eq_phrase = any(p in query_lower for p in _LIFESAVING_EQUIPMENT_PHRASES)
    if not (has_eq_token or has_eq_phrase):
        return ()
    return _MARKING_INTENT_VOCAB


def expand_intent(
    query: str, keywords: list[str],
) -> tuple[list[str], list[str]]:
    """Detect intent patterns and append canonical vocab to keywords.

    Each registered intent matcher (drill-frequency, equipment-marking,
    …) returns a tuple of vocab to append when its dual-signal gate
    fires. Multiple intents can fire on a single query — appended
    vocab is merged in registration order, deduped against the
    keyword set.

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

    # Run every registered intent. Each returns either an empty tuple
    # (didn't fire) or its canonical vocab additions.
    matchers = (
        _drill_frequency_intent,
        _equipment_marking_intent,
    )
    additions: list[str] = []
    for matcher in matchers:
        for v in matcher(query_lower, keyword_set):
            additions.append(v)

    if not additions:
        return list(keywords), []

    out = list(keywords)
    seen = set(keyword_set)
    added: list[str] = []
    for v in additions:
        v_lower = v.lower()
        if v_lower in seen:
            continue
        seen.add(v_lower)
        out.append(v)
        added.append(v)
    return out, added

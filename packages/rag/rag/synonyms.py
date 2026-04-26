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

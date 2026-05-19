"""Safety gold-set for synonyms.SYNONYM_DICT (D6.97).

Karynn's NVIC 01-86 hedge motivated adding the "coastwise" synonym to
bridge the shipping-articles vocabulary gap. The risk Blake flagged at
greenlight: the new synonym must NOT bleed into unrelated maritime
queries that share surface vocabulary.

Specifically: "discharge" appears in pollution-discharge, cargo-
discharge, electrical-discharge regulations. If our synonym expansion
accidentally surfaced NVIC 01-86 (crew discharge) for those queries,
we'd degrade retrieval on a wide swath of unrelated topics.

This test locks in the unidirectional discipline: keyword inputs from
unrelated discharge domains must NOT expand to crew-discharge / NVIC
01-86 vocabulary. If a future synonym addition breaks this, the test
fails before code ships.
"""
from __future__ import annotations

import pytest

from rag.synonyms import expand_keywords, SYNONYM_DICT


# Vocabulary that NVIC 01-86 / CG-705A retrieval is gated on. If any of
# these phrases appears in the expanded keywords for an unrelated
# discharge query, the synonym mapping has bled.
NVIC_01_86_PHRASES = (
    "voyage description",
    "particulars of engagement",
    "shipping articles",
)


# ── Unrelated 'discharge' queries that MUST NOT pull NVIC 01-86 ──────────
#
# Each tuple is (test_name, keyword_list). The keyword list is what
# would arrive at the retrieval layer after keyword extraction from a
# real user question on that topic.

UNRELATED_DISCHARGE_QUERIES: list[tuple[str, list[str]]] = [
    # MARPOL Annex I — oil pollution discharge into the sea
    ("pollution discharge — oil", ["oil", "discharge", "marpol", "annex"]),
    # 33 CFR 151 — vessel sewage discharge regulations
    ("pollution discharge — sewage", ["sewage", "discharge", "no-discharge", "zone"]),
    # 33 CFR 154 — facility oil transfer / cargo discharge
    ("cargo discharge — oil transfer", ["oil", "transfer", "cargo", "discharge"]),
    # 46 CFR 110.10 — electrical equipment grounding / arc discharge
    ("electrical discharge — arc protection", ["electrical", "arc", "discharge", "protection"]),
    # USCG marine casualty reporting — "discharge of pollutant"
    ("pollution discharge — reporting", ["discharge", "pollutant", "report", "casualty"]),
    # Bilge water discharge
    ("pollution discharge — bilge", ["bilge", "discharge", "oily", "water"]),
]


@pytest.mark.parametrize("scenario,keywords", UNRELATED_DISCHARGE_QUERIES)
def test_unrelated_discharge_query_does_not_pull_nvic_01_86(
    scenario: str, keywords: list[str],
) -> None:
    """The 'coastwise' synonym must not bleed into pollution / cargo /
    electrical discharge queries. The expansion is one-way from
    'coastwise' → NVIC vocabulary, NOT the reverse — these queries
    have no 'coastwise' keyword so the expansion must not fire."""
    expanded, synonym_map = expand_keywords(keywords)
    expanded_lower = [k.lower() for k in expanded]
    for phrase in NVIC_01_86_PHRASES:
        assert phrase not in expanded_lower, (
            f"REGRESSION: scenario {scenario!r} (keywords={keywords}) "
            f"expanded to include {phrase!r}, which is NVIC 01-86 "
            f"shipping-articles vocabulary. The synonym mapping should "
            f"be one-way from 'coastwise' → NVIC; the reverse direction "
            f"causes degradation on unrelated discharge queries. "
            f"Full expanded keywords: {expanded}. "
            f"Synonym map: {synonym_map}"
        )


# ── 'coastwise' query DOES expand to NVIC vocab (positive case) ──────────


def test_coastwise_keyword_pulls_nvic_01_86_vocab() -> None:
    """Sanity check the positive direction: when 'coastwise' IS a
    keyword, the NVIC 01-86 shipping-articles vocabulary is added.
    This is the Karynn hedge fix — without this expansion, her
    'Foreign vs Coastwise box on CG-705A' query top-1 retrieval was
    0.016 cosine (noise)."""
    expanded, synonym_map = expand_keywords(["coastwise", "box"])
    expanded_lower = [k.lower() for k in expanded]
    for phrase in NVIC_01_86_PHRASES:
        assert phrase in expanded_lower, (
            f"'coastwise' keyword must expand to {phrase!r}. "
            f"Got expanded={expanded}, synonym_map={synonym_map}"
        )
    # The mapping is one-way: 'coastwise' is the key.
    assert "coastwise" in synonym_map
    assert set(NVIC_01_86_PHRASES) <= {s.lower() for s in synonym_map["coastwise"]}


# ── No 'coastwise' phrase reverse-maps into any existing key ──────────


def test_coastwise_expansion_targets_are_not_synonym_keys() -> None:
    """The NVIC vocabulary phrases ('voyage description', etc.) must
    NOT appear as keys in SYNONYM_DICT — otherwise a cycle could form
    where typing 'voyage description' triggers a different expansion
    that re-pulls 'coastwise' or worse. Defensive invariant for any
    future maintainer adding NVIC-related synonyms."""
    for phrase in NVIC_01_86_PHRASES:
        assert phrase not in SYNONYM_DICT, (
            f"{phrase!r} should not be a SYNONYM_DICT key — it's an "
            f"expansion target. Making it a key risks creating a cycle "
            f"or unintended cross-mapping."
        )


# ── Other unrelated maritime queries that share words with NVIC ──────────


def test_jones_act_coastwise_trade_not_polluted() -> None:
    """'coastwise trade' (Jones Act, 46 USC 55102) is a different
    regulatory domain from 'shipping articles voyage description'.
    However, because 'coastwise' is the trigger keyword, expansion
    DOES fire — by design — to widen the retrieval net. We accept
    the small cross-contamination because Jones Act questions land
    enough corpus chunks on their own (§ 55102 has 1 chunk + Subtitle
    V Ch.551 has 39 sections) that adding NVIC phrases as auxiliary
    matches is harmless. This test documents the trade-off so we
    don't surprise ourselves later."""
    expanded, _ = expand_keywords(["coastwise", "trade", "jones", "act"])
    # NVIC phrases DO get added — this is the intentional behavior
    # of the keyword-keyed expansion mechanism.
    expanded_lower = [k.lower() for k in expanded]
    for phrase in NVIC_01_86_PHRASES:
        assert phrase in expanded_lower, (
            f"Expected NVIC phrase {phrase!r} to be added even on a "
            f"Jones Act query (since 'coastwise' is the trigger). "
            f"If we ever want to suppress this, the right fix is to "
            f"make the synonyms map context-aware, not silently change "
            f"this test."
        )
    # But the Jones Act keywords themselves are preserved — retrieval
    # still has the right primary signal.
    assert "jones" in expanded_lower
    assert "trade" in expanded_lower

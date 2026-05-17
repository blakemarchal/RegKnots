"""Gold-set tests for the maritime current-events trigger detector.

Sprint D6.96 — these tests encode the discipline we promised Blake at
greenlight: regulatory questions that happen to contain temporal words
must NEVER trip the news path. Any change to the trigger lists in
``current_events_triggers.py`` runs these tests; a regression here is a
blocker.

Test case #1 is intentionally Blake's exact greenlight query — the
phrasing that motivated the two-tier detector design. It is locked in
as the canonical regression case.
"""
from __future__ import annotations

import pytest

from rag.current_events_triggers import detect_current_events_intent


# ── REGULATORY queries that must NOT fire the news path ──────────────────
#
# These are the queries that must always route to corpus-only retrieval.
# They contain temporal markers but the regulatory anchor must veto them.

REGULATORY_QUERIES = [
    # Blake's greenlight query — locked-in regression case
    "As of today, what's the most recent IMO amendment relevant to my ship right now?",
    # Variants of "latest <regulation>" — common shape for regulatory questions
    "What's the latest MARPOL Annex VI amendment about?",
    "Latest USCG MSIB on lithium batteries",
    "Recent NVIC on TWIC enforcement",
    "What's the most recent Lloyd's Notice?",
    "What does the latest STCW amendment say about ECDIS?",
    "Most recent 46 CFR 11 amendment",
    "Current 46 CFR 199.175 text for passenger vessels",
    "Latest MSC resolution adopted by IMO",
    "Recent MEPC.367(79) MARPOL amendment",
    "What is the current ISM Code text on safety management?",
    "Latest SOLAS Chapter III amendment for survival craft",
    "Recent ABS MVR Part 4 changes",
    "Most recent IACS UR on hull construction",
    "Latest USCG policy letter on credentialing",
    "What's the most recent change to 46 USC 8104?",
    "Current AMSA Marine Order 21 text",
    "Recent MCA MGN on lifejacket inspection",
    "What's the latest ballast water management regulation?",
    "Current Polar Code requirements for ice navigation",
    "Latest LR-CO-001 amendment",
    "Most recent OCIMF SIRE guidelines",
    "What's the current text of 33 CFR 164.78?",
    "Latest WHO IHR annex 3 ship sanitation requirements",
]


@pytest.mark.parametrize("query", REGULATORY_QUERIES)
def test_regulatory_query_does_not_fire_news(query: str) -> None:
    """Regulatory questions with temporal markers must suppress the news
    path. The presence of a regulatory anchor (CFR, USC, IMO, MARPOL,
    STCW, USCG, NVIC, etc.) is the discipline that protects the
    verified-citation tier from news contamination."""
    fired, markers = detect_current_events_intent(query)
    assert fired is False, (
        f"REGRESSION: '{query}' fired the news path. "
        f"Matched markers: {markers}. The regulatory anchor should have "
        f"vetoed any weak temporal triggers."
    )


# ── CURRENT-EVENTS queries that MUST fire the news path ──────────────────
#
# These are the queries where we want the news path to fire alongside
# corpus retrieval so the synthesizer can deliver the hybrid framework +
# current-reading answer that started this whole sprint.

CURRENT_EVENTS_QUERIES = [
    # Nicholas's original Jones Act waiver question — locked-in case
    "Tell me exactly what's happening with the jones act waivers currently, "
    "why is it bad for the marine industry and who do the waivers benefit",
    # Strong news-shape patterns (Tier 1)
    "What's happening with the Strait of Hormuz right now?",
    "Why is the Houthi attack on shipping bad for trade?",
    "Who benefits from the Russia sanctions on tanker shipping?",
    "What's the impact of the Panama drought on transit times?",
    "How will this affect Red Sea voyage planning?",
    "Any updates on the Suez Canal situation?",
    "Any news on the ILA strike?",
    "What's the latest on the Jones Act waiver debate?",
    # Named hot topics (Tier 2) — fire even without question-shape signal
    "Strait of Hormuz transit security",
    "Red Sea routing for tankers",
    "Houthi missile attack on commercial vessels",
    "Russia shadow fleet enforcement",
    "Panama drought 2026 vessel restrictions",
    "Hurricane waiver issued by DHS",
    "Iran tankers seizure",
    # Weak temporal + no regulatory anchor (Tier 3)
    "What's currently affecting West Coast container traffic?",
    "Latest on tariffs affecting maritime trade",
    "Recent events impacting the Suez Canal",
    # Hybrid intent — strong pattern wins over reg anchor
    "What's happening with the new MARPOL VLSFO regulation?",
    "Why is the new Jones Act amendment bad for operators?",
]


@pytest.mark.parametrize("query", CURRENT_EVENTS_QUERIES)
def test_current_events_query_fires_news(query: str) -> None:
    """Current-events questions must fire the news path so the
    synthesizer can pull in trusted-source commentary alongside any
    corpus-grounded regulatory framework."""
    fired, markers = detect_current_events_intent(query)
    assert fired is True, (
        f"REGRESSION: '{query}' did NOT fire the news path. "
        f"Matched markers: {markers}. This question expected to route "
        f"to the trusted-news web fallback path."
    )


# ── Specific behavioral tests ────────────────────────────────────────────


def test_blake_greenlight_query_is_locked_in() -> None:
    """The exact query Blake used at greenlight as the false-positive
    pressure-test. If this ever fires news, the discipline has slipped
    and the whole feature should be paused until the trigger lists are
    re-audited."""
    query = (
        "As of today, what's the most recent IMO amendment relevant to "
        "my ship right now?"
    )
    fired, markers = detect_current_events_intent(query)
    assert fired is False, (
        f"BLAKE-GUARDED REGRESSION: this is the query that motivated "
        f"the two-tier detector design. It must never fire news. "
        f"Matched: {markers}"
    )
    # The veto should be visible in the markers so logging can audit.
    assert any(m.startswith("anchor_veto:") for m in markers), (
        f"Expected to see an anchor_veto marker. Got: {markers}"
    )


def test_nicholas_jones_act_query_fires_news() -> None:
    """The Jones Act waiver question that started this whole sprint —
    locks in the positive case symmetrically with Blake's negative."""
    query = (
        "Tell me exactly what's happening with the jones act waivers "
        "currently, why is it bad for the marine industry and who do "
        "the waivers benefit"
    )
    fired, markers = detect_current_events_intent(query)
    assert fired is True
    # Multiple strong markers expected (what's happening with, why is,
    # who benefits, jones act waiver hot topic)
    strong_count = sum(1 for m in markers if m.startswith("strong:"))
    assert strong_count >= 2, (
        f"Expected multiple strong patterns; got {strong_count}: {markers}"
    )


def test_strong_pattern_overrides_regulatory_anchor() -> None:
    """When a user uses a clearly news-shaped question ABOUT a
    regulation ('why is the new SOLAS amendment bad'), the news path
    fires — they're asking for commentary on the regulation, not the
    regulation text itself. Corpus still pulls the regulation; news
    adds the commentary layer."""
    query = "Why is the new MARPOL Annex VI 2025 amendment bad for operators?"
    fired, markers = detect_current_events_intent(query)
    assert fired is True
    # The 'why is' strong pattern should appear in markers
    assert any(m.startswith("strong:") for m in markers)


def test_weak_only_no_anchor_fires_news() -> None:
    """Temporal-only queries without a clear topic still fire news so
    we can attempt to find recent maritime context. The bar is low here
    intentionally — bias is to try news rather than miss."""
    query = "What's currently affecting shipping in the Gulf of Mexico?"
    fired, markers = detect_current_events_intent(query)
    assert fired is True


def test_pure_regulatory_question_no_markers() -> None:
    """Sanity check: a clean regulatory question with no temporal words
    or news patterns produces no markers and does not fire news."""
    query = "What does 46 CFR 199.175 require for survival craft?"
    fired, markers = detect_current_events_intent(query)
    assert fired is False
    assert markers == []


def test_empty_query_does_not_fire() -> None:
    """Defensive: empty or whitespace queries return False without
    raising."""
    for q in ["", "   ", "\n\t"]:
        fired, markers = detect_current_events_intent(q)
        assert fired is False
        assert markers == []


def test_case_insensitive_matching() -> None:
    """All triggers are case-insensitive — the user's casing should not
    matter."""
    queries = [
        "WHAT'S HAPPENING WITH THE STRAIT OF HORMUZ?",
        "What's Happening With The Strait Of Hormuz?",
        "what's happening with the strait of hormuz?",
    ]
    for q in queries:
        fired, _ = detect_current_events_intent(q)
        assert fired is True, f"Case-handling failed for: {q!r}"


def test_lloyds_ambiguity_resolved_correctly() -> None:
    """The bare 'lloyd's' anchor vetoes the news path for regulatory
    questions ('Lloyd's Notice'). Genuine news questions about Lloyd's
    contexts (Lloyd's List reporting, Lloyd's of London market) still
    fire news when a Tier 1 strong pattern or Tier 2 hot topic catches
    them, because Tier 1/2 fire regardless of anchors."""
    # Regulatory: Lloyd's Notice → suppressed
    fired, _ = detect_current_events_intent("What's the most recent Lloyd's Notice?")
    assert fired is False, "Lloyd's Notice (regulatory) must not fire news"

    # Lloyd's List news with Tier 2 hot topic: still fires
    fired, _ = detect_current_events_intent(
        "What is Lloyd's List reporting on the Red Sea situation?"
    )
    assert fired is True, "Lloyd's List + Red Sea (Tier 2 hot topic) must fire news"

    # Lloyd's-related news with Tier 1 strong pattern: still fires
    fired, _ = detect_current_events_intent(
        "What's happening with Lloyd's of London marine insurance rates?"
    )
    assert fired is True, "Lloyd's + 'what's happening with' (Tier 1) must fire news"

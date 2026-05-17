"""Detect maritime current-events questions vs regulatory questions.

Sprint D6.96 — when a user asks about a current event ("what's happening
with Jones Act waivers right now"), the chat needs to fire an
additional news-domain web fallback alongside corpus retrieval. But the
detector must NEVER mistake a regulatory question that happens to
contain temporal words ("As of today, what's the most recent IMO
amendment for my ship?") for a current-events question. Doing so would
add news noise to a clean regulatory answer and degrade the chat's
verified-citation rigor — the exact failure mode Blake flagged at
greenlight.

Three tiers, evaluated in order:

  TIER 1 — STRONG news patterns (always fire news, even with anchors).
    Question shapes that are inherently news/policy:
    "what's happening with", "any updates on", "why is", "who benefits".
    A regulation-anchored version like "why is the new MARPOL amendment
    bad" still wants the news layer because the user is asking for
    commentary ON the regulation, not just the regulation text.

  TIER 2 — Named hot topics (always fire news).
    Topics that are inherently current-events and not in any regulatory
    corpus we have: Hormuz, Houthi, Jones Act waiver activity, port
    strikes, sanctions, etc. These are moving stories that the news
    whitelist owns.

  TIER 3 — Weak temporal markers (fire only when no regulatory anchor).
    Words like "currently", "latest", "as of today", "most recent" appear
    constantly in legitimate regulatory questions ("latest STCW
    amendment", "current 46 CFR text"). Tier 3 fires the news path ONLY
    when no regulatory anchor is present in the query. This is the
    discipline that protects the regulatory tier.

Bias: when uncertain, suppress news. Better to under-trigger than to
ever degrade a regulatory answer. Users who want news context can be
explicit ("what's happening with X").

The detection runs in-process (<1ms) on every query. No LLM call.
Telemetry logs the matched tier + which markers fired so we can audit
miscalls and tune the lists from real traffic.
"""
from __future__ import annotations

# ── Tier 1: strong news-shape patterns (always fire) ──────────────────────
#
# These question patterns are inherently news/policy regardless of
# regulatory anchors. Asking "why is the new SOLAS amendment bad" IS a
# current-events question even though it mentions SOLAS — the user is
# asking for commentary, not the regulation text.
_STRONG_NEWS_PATTERNS: tuple[str, ...] = (
    "what's happening with",
    "what is happening with",
    "any updates on",
    "any news on",
    "what's the latest on",
    "what is the latest on",
    "why is",          # "why is the Jones Act bad"
    "who benefits",
    "who's affected",
    "who is affected",
    "what's the impact",
    "what is the impact",
    "how will this affect",
    "how does this affect",
)


# ── Tier 2: named hot topics (always fire) ────────────────────────────────
#
# Topics inherently in current-events territory; we don't have them in
# any regulatory corpus. Add new entries here as they emerge (port
# strikes, named events, etc.). Quarterly curation review.
_HOT_TOPICS: tuple[str, ...] = (
    # Jones Act + waiver activity
    "jones act waiver", "hurricane waiver", "fuel waiver", "lng waiver",
    # Maritime chokepoints with active conflict/disruption
    "strait of hormuz", "red sea", "houthi", "houthis",
    "bab el-mandeb", "bab al-mandeb",
    "suez canal", "panama drought",
    # Sanctions regimes
    "russia sanctions", "russian sanctions", "iran sanctions",
    "iran tankers", "shadow fleet", "dark fleet",
    # Labor / port disruptions
    "port strike", "longshoremen", "ila strike", "ilwu strike",
    "dockworker strike",
    # Casualty / spill events (kept generic — specific event names go
    # in when they're current)
    "current oil spill",
)


# ── Tier 3: weak temporal markers (suppressed by regulatory anchors) ──────
#
# These words appear in BOTH news questions ("currently") and regulatory
# questions ("most recent STCW amendment"). They count as current-events
# signals ONLY when no regulatory anchor is present in the query.
_WEAK_TEMPORAL: tuple[str, ...] = (
    "currently",
    "right now",
    "as of today",
    "as of now",
    "latest",
    "most recent",
    "recent",
    "this week",
    "this month",
)


# ── Regulatory anchors that veto Tier 3 ───────────────────────────────────
#
# Presence of any of these in the query means the user is asking about a
# regulation that is recent/current — not asking for news. Tier 3 weak
# triggers do NOT fire news when an anchor is present. Tier 1 + Tier 2
# fire regardless (they're stronger intent signals).
_REGULATORY_ANCHORS: tuple[str, ...] = (
    # Statutes + federal regulations
    " cfr ", " cfr.", " cfr,", "cfr part", "cfr §", " usc ", " usc.",
    " usc,", "usc §", "title 46", "title 33", "title 49",
    # Major IMO conventions / codes
    "solas", "marpol", "stcw", "ism code", "isps", "imdg", "colreg",
    "colregs", "iamsar", "load line", "loadlines", "polar code",
    "igf code", "igc code", "ibc code", "hsc code", "bwm", "ballast water",
    "who ihr", " ihr ",
    # Convention machinery
    "imo amend", "imo amendment", "msc resolution", "mepc resolution",
    "msc.", "mepc.", " amendment ", "regulation ", " circular ",
    "code amend", " annex ",
    # Class society / industry standards
    "abs mvr", "abs rule", "abs guide", "abs notice",
    # 'lloyd's' is ambiguous (Lloyd's Register vs. Lloyd's List news
    # outlet vs. Lloyd's of London insurance). In maritime regulatory
    # questions it almost always means Lloyd's Register. Genuine news
    # questions that happen to mention Lloyd's typically hit Tier 1
    # ('what's happening with') or Tier 2 (a named topic) which fire
    # news regardless of this anchor.
    "lloyd's", "lloyds ", "lr-co", "lr-ru", "lr notice",
    "dnv rule", "dnv notice", "classnk", "bureau veritas",
    "iacs ur", "iacs pr", "ocimf",
    # USCG / federal guidance
    "uscg ", "u.s. coast guard", "us coast guard", "nvic", "msib",
    "alcoast", "nmc policy", "nmc checklist", "msm", "marine safety manual",
    "policy letter",
    # Flag-state regulators
    "mca mgn", "mca msn", "amsa marine order", "amsa mo", "mardep",
    "marshall islands marine notice", "iri ", "liscr", "bma marine notice",
    "mpa singapore", "tc canada", "nma norway",
)


def detect_current_events_intent(query: str) -> tuple[bool, list[str]]:
    """Return (should_fire_news, matched_markers) for a query.

    The second element is the list of markers that triggered (or the
    list of regulatory anchors that suppressed the weak path). Used by
    the logging layer to populate ``current_events_responses.markers_matched``
    so we can audit miscalls from real traffic.

    Three-tier algorithm — see module docstring for the design rationale.
    """
    q = query.lower()
    matched: list[str] = []

    # Tier 1: strong news-shape patterns fire news unconditionally.
    for p in _STRONG_NEWS_PATTERNS:
        if p in q:
            matched.append(f"strong:{p}")
    if matched:
        return True, matched

    # Tier 2: named hot topics fire news unconditionally.
    for t in _HOT_TOPICS:
        if t in q:
            matched.append(f"hot_topic:{t}")
    if matched:
        return True, matched

    # Tier 3: weak temporal markers fire only when no anchor present.
    for w in _WEAK_TEMPORAL:
        if w in q:
            matched.append(f"weak:{w}")
    if not matched:
        return False, []

    # Check for regulatory anchors that veto the weak path.
    for a in _REGULATORY_ANCHORS:
        if a in q:
            return False, matched + [f"anchor_veto:{a.strip()}"]

    # Weak trigger, no anchor → news path fires.
    return True, matched

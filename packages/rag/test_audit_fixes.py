"""Tests for the 2026-06 quality-audit fixes (Sprint D6.97).

1. followup.compose_reason — short mid-thread messages compose with the
   prior user message even when no pushback pattern matches (Nirmal's
   2026-06-04 provisions thread). Decoupled from detect_followup, which
   stays narrow because it also gates the Opus escalation.

2. retriever._extract_identifiers — USCG form numbers (CG-835 etc.)
   become identifiers. Bare numbers in form context resolve to the
   CG-prefixed form search. Karynn's 2026-06-04 "self reported 835"
   produced empty keywords AND empty identifiers before this fix.
"""
from __future__ import annotations

from rag.followup import compose_reason, detect_followup
from rag.retriever import _extract_identifiers, _extract_keywords


# ── compose_reason ──────────────────────────────────────────────────────


def test_short_midthread_message_composes():
    """Nirmal's exact clarifications matched no pushback pattern but are
    short mid-thread → must compose."""
    for q in [
        "The question is about USCG best before date rule",
        "I am talking about General provisions for daily consumption",
    ]:
        assert detect_followup(q) is None, f"should not pattern-match: {q!r}"
        assert compose_reason(q, history_len=2) is not None, (
            f"short mid-thread should compose: {q!r}"
        )
        # First turn (no history) must NOT compose.
        assert compose_reason(q, history_len=0) is None


def test_pattern_message_composes_and_reports_pattern():
    q = "you said NAVTEX was decommissioned"
    reason = compose_reason(q, history_len=2)
    assert reason is not None and reason.startswith("pattern:")


def test_long_standalone_midthread_does_not_compose():
    """A long, self-contained mid-thread question carries its own topical
    anchor — no pattern, over the length threshold → no composition."""
    q = (
        "Inflatable liferafts on a US-flag containership over 500 gross "
        "tons making international voyages have which carriage and "
        "servicing-interval requirements, and where must they be stowed "
        "under SOLAS Chapter III and 46 CFR Subchapter W rules?"
    )
    assert detect_followup(q) is None, "fixture must not match a pattern"
    assert len(q) >= 140
    assert compose_reason(q, history_len=2) is None


def test_short_reason_encodes_length():
    reason = compose_reason("best before rule?", history_len=1)
    assert reason is not None and reason.startswith("short:")


# ── CG-form identifiers ─────────────────────────────────────────────────


def _cg_patterns(ids):
    return [i["value"] for i in ids if i.get("type", "").startswith("cg_form")]


def test_explicit_cg_form_extracted():
    for q, expect in [
        ("What is a CG-835?", "CG-835"),
        ("How do I fill out CG 719B", "CG-719B"),
        ("CG2692 casualty report deadline", "CG-2692"),
    ]:
        ids = _extract_identifiers(q)
        assert expect in _cg_patterns(ids), f"{q!r} → {_cg_patterns(ids)}"


def test_bare_number_in_form_context_resolves_to_cg_form():
    """Karynn's exact query — bare '835', no CG prefix, but 'reported'
    is form context → search the CG-prefixed form."""
    q = "How do I send a self reported 835 for sailing short"
    ids = _extract_identifiers(q)
    assert "CG-835" in _cg_patterns(ids), _cg_patterns(ids)
    # Regex search (not bare-number ILIKE) so we hit CG-835 not stray 835s.
    cg = next(i for i in ids if i["value"] == "CG-835")
    assert cg.get("regex") is True
    assert "[Cc][Gg]" in cg["pattern"]


def test_bare_number_without_form_context_does_not_fire():
    """A bare number with no form-context word must NOT become a CG form
    — avoids 'within 12 hours' / 'carry 2 copies' noise."""
    q = "How many liferafts within 120 minutes of the muster"
    ids = _extract_identifiers(q)
    assert _cg_patterns(ids) == [], _cg_patterns(ids)


def test_two_digit_bare_number_excluded_in_form_context():
    """Form context present, but a 2-digit number is too short to be a
    CG form — excluded (3-digit minimum for the bare path)."""
    q = "submit the report within 12 hours"
    ids = _extract_identifiers(q)
    assert "CG-12" not in _cg_patterns(ids)


def test_cg_form_query_no_longer_blind():
    """The audit's smoking gun: this produced empty keywords AND empty
    identifiers. Now it must produce at least the CG-835 identifier."""
    q = "How do I send a self reported 835 for sailing short"
    assert _extract_identifiers(q), "identifiers must be non-empty now"

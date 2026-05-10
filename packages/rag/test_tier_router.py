"""Unit tests for the confidence tier router (Sprint D6.84).

Runs without a database, OpenAI key, or live Anthropic calls — every
LLM round-trip is mocked. Covers the routing decision tree + the
pure helper functions.

Usage:
    uv run python test_tier_router.py     (standalone, prints PASS/FAIL)
    uv run pytest test_tier_router.py     (pytest discovery; same tests)
"""
from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

# Ensure local rag/ package import works whether pytest or python invokes.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from rag.tier_router import (
    TIER_BEST_EFFORT,
    TIER_INDUSTRY_STANDARD,
    TIER_RELAXED_WEB,
    TIER_VERIFIED,
    _INDUSTRY_FOOTNOTE_MARKER,
    render_industry_standard_answer,
    route_tier,
)


# ── Fakes ────────────────────────────────────────────────────────────


@dataclass
class FakeWebFallback:
    """Stand-in for WebFallbackCard. Only `confidence` is read by the
    routing logic, the rest is preserved for shadow-log fields."""
    confidence: int
    source_url: str = "https://example.com"
    source_domain: str = "example.com"
    quote: str = ""
    summary: str = "summary"
    fallback_id: str = "fb-1"
    surface_tier: str = "verified"


class FakeBlock:
    type = "text"
    def __init__(self, text: str) -> None:
        self.text = text


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.content = [FakeBlock(text)]


class FakeAnthropicClient:
    """Mock AsyncAnthropic.messages.create — returns scripted responses
    in order. Each .create() call pops the next scripted text.
    """
    def __init__(self, scripted: list[str]) -> None:
        self.messages = self  # so .messages.create works
        self._scripted = list(scripted)
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._scripted:
            return FakeMessage('{"verdict":"no","reasoning":"no script left"}')
        return FakeMessage(self._scripted.pop(0))


# ── Helpers ─────────────────────────────────────────────────────────


def _ok():
    print("  PASS")


def _fail(msg: str):
    print(f"  FAIL — {msg}")
    raise AssertionError(msg)


def _check(cond: bool, msg: str = ""):
    if not cond:
        _fail(msg or "assertion failed")


# ── Pure-helper tests ───────────────────────────────────────────────


def test_render_industry_standard_appends_footnote():
    print("test_render_industry_standard_appends_footnote")
    out = render_industry_standard_answer("The answer is closed-cell.")
    _check(_INDUSTRY_FOOTNOTE_MARKER in out, "marker not present")
    _check("The answer is closed-cell." in out, "original answer dropped")
    _ok()


def test_render_industry_standard_idempotent():
    print("test_render_industry_standard_idempotent")
    once = render_industry_standard_answer("X.")
    twice = render_industry_standard_answer(once)
    _check(once == twice, "second call mutated already-footnoted answer")
    _ok()


# ── route_tier branch tests ─────────────────────────────────────────


async def test_tier1_verified_with_judge_match():
    print("test_tier1_verified_with_judge_match")
    client = FakeAnthropicClient([])
    decision = await route_tier(
        query="What are the lifeboat inspection intervals for class III vessels?",
        cleaned_answer="Per 46 CFR 199.180, lifeboats are inspected weekly.",
        verified_citations_count=2,
        judge_verdict=None,  # no hedge → strong verified signal
        web_fallback_card=None,
        anthropic_client=client,
    )
    _check(decision.tier == 1, f"expected tier 1, got {decision.tier}")
    _check(decision.label == TIER_VERIFIED)
    _check(decision.rendered_answer is None, "tier 1 should not rewrite the answer")
    _check(len(client.calls) == 0, "tier 1 must not call the classifier (cost saver)")
    _ok()


async def test_tier1_verified_with_precision_callout():
    print("test_tier1_verified_with_precision_callout")
    client = FakeAnthropicClient([])
    decision = await route_tier(
        query="When can a work vest be substituted?",
        cleaned_answer="Long answer with 8 citations + 'btw the niche detail isn't in my context'.",
        verified_citations_count=5,
        judge_verdict="precision_callout",
        web_fallback_card=None,
        anthropic_client=client,
    )
    _check(decision.tier == 1, f"precision_callout with citations should stay tier 1, got {decision.tier}")
    _check(len(client.calls) == 0, "precision_callout must not call classifier")
    _ok()


async def test_tier3_high_confidence_web_outranks_tier2():
    """Per the design: a verifiable USCG.mil-grade web source (conf ≥4)
    beats unsourced industry knowledge."""
    print("test_tier3_high_confidence_web_outranks_tier2")
    client = FakeAnthropicClient([])  # classifier should NOT be called
    decision = await route_tier(
        query="Edge case where corpus is empty but the web has a great source.",
        cleaned_answer="hedged answer",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=FakeWebFallback(confidence=4),
        anthropic_client=client,
    )
    _check(decision.tier == 3, f"high-conf web should be tier 3, got {decision.tier}")
    _check(decision.label == TIER_RELAXED_WEB)
    _check(decision.web_confidence == 4)
    _check(len(client.calls) == 0, "high-conf web should short-circuit before classifier fires")
    _ok()


async def test_tier2_industry_standard_classifier_yes_self_consistency_pass():
    """The Jordan gasket case: corpus empty, classifier YES, regen agrees."""
    print("test_tier2_industry_standard_classifier_yes_self_consistency_pass")
    client = FakeAnthropicClient([
        # 1) classifier
        '{"verdict":"yes","reasoning":"closed-cell elastomer is settled engineering"}',
        # 2) regenerated answer (low temp)
        "Closed-cell elastomer. Open-cell absorbs water and loses seal under pressure.",
        # 3) comparator
        '{"verdict":"agree","reasoning":"both say closed-cell"}',
    ])
    decision = await route_tier(
        query="Should a watertight door gasket be open or closed cell material?",
        cleaned_answer="Watertight door gaskets should be closed-cell elastomer.",
        verified_citations_count=0,
        judge_verdict="partial_miss",
        web_fallback_card=FakeWebFallback(confidence=2),  # below threshold for tier 3
        anthropic_client=client,
    )
    _check(decision.tier == 2, f"expected tier 2, got {decision.tier}")
    _check(decision.label == TIER_INDUSTRY_STANDARD)
    _check(decision.classifier_verdict == "yes")
    _check(decision.self_consistency_pass is True)
    _check(decision.rendered_answer is not None, "tier 2 should rewrite with footnote")
    _check(_INDUSTRY_FOOTNOTE_MARKER in decision.rendered_answer)
    _check(len(client.calls) == 3, f"expected 3 calls (classifier+regen+comparator), got {len(client.calls)}")
    _ok()


async def test_tier4_when_classifier_yes_but_self_consistency_fails():
    """Classifier said yes but the regen disagreed → downgrade to tier 4
    rather than promoting an unstable answer."""
    print("test_tier4_when_classifier_yes_but_self_consistency_fails")
    client = FakeAnthropicClient([
        '{"verdict":"yes","reasoning":"looks settled"}',
        "Some divergent regen.",
        '{"verdict":"disagree","reasoning":"a says X, b says Y"}',
    ])
    decision = await route_tier(
        query="Some maritime question.",
        cleaned_answer="Original answer.",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=None,  # no web safety net
        anthropic_client=client,
    )
    _check(decision.tier == 4, f"sc fail with no web should be tier 4, got {decision.tier}")
    _check(decision.label == TIER_BEST_EFFORT)
    _check(decision.self_consistency_pass is False)
    _check(decision.classifier_verdict == "yes")
    _check(decision.rendered_answer is None, "tier 4 should not rewrite")
    _ok()


async def test_tier3_relaxed_web_when_classifier_no_and_web_present():
    print("test_tier3_relaxed_web_when_classifier_no_and_web_present")
    client = FakeAnthropicClient([
        '{"verdict":"no","reasoning":"specific regulatory threshold"}',
    ])
    decision = await route_tier(
        query="What is the maximum allowable PCB concentration in shipboard waste oil?",
        cleaned_answer="hedged answer",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=FakeWebFallback(confidence=3),
        anthropic_client=client,
    )
    _check(decision.tier == 3, f"expected tier 3 relaxed, got {decision.tier}")
    _check(decision.label == TIER_RELAXED_WEB)
    _check(decision.web_confidence == 3)
    _check(decision.classifier_verdict == "no")
    _ok()


async def test_tier4_when_everything_fails():
    print("test_tier4_when_everything_fails")
    client = FakeAnthropicClient([
        '{"verdict":"no","reasoning":"regulatory in nature"}',
    ])
    decision = await route_tier(
        query="Specific regulatory question we have nothing for.",
        cleaned_answer="hedged answer",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=None,
        anthropic_client=client,
    )
    _check(decision.tier == 4)
    _check(decision.label == TIER_BEST_EFFORT)
    _check(decision.rendered_answer is None)
    _ok()


async def test_classifier_uncertain_treated_as_no():
    """UNCERTAIN must NOT promote to tier 2 — fail-safe."""
    print("test_classifier_uncertain_treated_as_no")
    client = FakeAnthropicClient([
        '{"verdict":"uncertain","reasoning":"ambiguous"}',
    ])
    decision = await route_tier(
        query="Borderline question.",
        cleaned_answer="hedged",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=FakeWebFallback(confidence=3),
        anthropic_client=client,
    )
    _check(decision.tier == 3, "uncertain classifier should fall to tier 3 if web available")
    _check(decision.classifier_verdict == "uncertain")
    _ok()


async def test_classifier_api_failure_falls_through_to_tier3_or_tier4():
    """Anthropic API error during classifier → uncertain → fall through."""
    print("test_classifier_api_failure_falls_through_to_tier3_or_tier4")

    class BoomClient:
        def __init__(self):
            self.messages = self
        async def create(self, **kwargs):
            raise RuntimeError("simulated API error")

    decision = await route_tier(
        query="Anything.",
        cleaned_answer="hedged",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=FakeWebFallback(confidence=3),
        anthropic_client=BoomClient(),
    )
    # Classifier failed → uncertain → tier 3 (web available) or tier 4 (no web)
    _check(decision.tier in (3, 4))
    _check(decision.classifier_verdict == "uncertain")
    _ok()


async def test_malformed_classifier_json_treated_as_uncertain():
    print("test_malformed_classifier_json_treated_as_uncertain")
    client = FakeAnthropicClient([
        "garbage non-JSON output without braces",
    ])
    decision = await route_tier(
        query="anything",
        cleaned_answer="hedged",
        verified_citations_count=0,
        judge_verdict="complete_miss",
        web_fallback_card=None,
        anthropic_client=client,
    )
    _check(decision.classifier_verdict == "uncertain")
    _check(decision.tier == 4)
    _ok()


# ── Runner ──────────────────────────────────────────────────────────


async def _run_all():
    test_render_industry_standard_appends_footnote()
    test_render_industry_standard_idempotent()
    await test_tier1_verified_with_judge_match()
    await test_tier1_verified_with_precision_callout()
    await test_tier3_high_confidence_web_outranks_tier2()
    await test_tier2_industry_standard_classifier_yes_self_consistency_pass()
    await test_tier4_when_classifier_yes_but_self_consistency_fails()
    await test_tier3_relaxed_web_when_classifier_no_and_web_present()
    await test_tier4_when_everything_fails()
    await test_classifier_uncertain_treated_as_no()
    await test_classifier_api_failure_falls_through_to_tier3_or_tier4()
    await test_malformed_classifier_json_treated_as_uncertain()


if __name__ == "__main__":
    print("Running tier_router unit tests…")
    asyncio.run(_run_all())
    print("\nAll tier_router tests PASSED")

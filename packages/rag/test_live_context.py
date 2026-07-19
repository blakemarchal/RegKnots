"""Tests for rag/live_context.py — 2026-07-19 Wk3 live-context injectors."""

from rag.live_context import detect_live_context, window_days_for_query


class TestRegChangeDetection:
    def test_what_changed_recently(self):
        assert detect_live_context("What changed recently in the regulations?") == "reg_changes"

    def test_whats_new(self):
        assert detect_live_context("what's new in the corpus this week") == "reg_changes"

    def test_recent_amendments(self):
        assert detect_live_context("Any recent amendments I should know about?") == "reg_changes"

    def test_new_regs_last_month(self):
        assert detect_live_context("new regulations in the last month for tankers") == "reg_changes"

    def test_changelog(self):
        assert detect_live_context("show me the changelog") == "reg_changes"

    def test_topic_question_not_triggered(self):
        # "new construction" is a topic, not a recency ask — must NOT trip.
        assert detect_live_context("What are the new construction requirements for tank vessels?") is None

    def test_plain_regulation_question_not_triggered(self):
        assert detect_live_context("How many fire extinguishers does my towboat need?") is None

    def test_renewal_question_not_triggered(self):
        assert detect_live_context("What do I need to renew my MMC?") is None


class TestWhaleZoneDetection:
    def test_active_whale_zones(self):
        assert detect_live_context("Which whale zones are active right now?") == "whale_zones"

    def test_seasonal_management_area(self):
        assert detect_live_context("Am I transiting a seasonal management area?") == "whale_zones"

    def test_right_whale(self):
        assert detect_live_context("right whale speed restrictions off Georgia") == "whale_zones"

    def test_ten_knot_rule(self):
        assert detect_live_context("where does the 10-knot rule apply today") == "whale_zones"

    def test_whale_beats_reg_change(self):
        # Both intents present → whale wins (more specific data need).
        assert detect_live_context("any recent updates to whale zones?") == "whale_zones"


class TestWindowDays:
    def test_default(self):
        assert window_days_for_query("what changed recently?") == 30

    def test_week(self):
        assert window_days_for_query("what changed this week?") == 7

    def test_month(self):
        assert window_days_for_query("updates in the past month") == 30

    def test_quarter(self):
        assert window_days_for_query("this quarter's changes") == 90

    def test_year(self):
        assert window_days_for_query("everything new this year") == 365

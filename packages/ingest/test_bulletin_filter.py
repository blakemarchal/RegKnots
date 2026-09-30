"""2026-09-30 — uscg_bulletin: ephemeral / internal filter, feed discovery,
title-based prune plan (no network, no LLM)."""
import asyncio
from datetime import date

import pytest

from ingest.sources import uscg_bulletin as b


@pytest.mark.parametrize("subject,kind", [
    ("District 08 (GULF) Week 21LNM Now Available on Navigation Center Website", "outlook_or_lnm"),
    ("Hazardous Weather Outlook for the Western Atlantic", "outlook_or_lnm"),
    ("SAFETY/LA - SUNSHINE BRIDGE/HAZARD/SEC NOLA BNM 0560-26", "broadcast_notice"),
    ("CANCELLATION - MULTIPLE/SEC BUF", "broadcast_notice"),
    ("UMIB/MD - 28NM EAST OF OCEAN CITY, MD/DISTRESS/CCGD5 UMIB 1000-25", "broadcast_notice"),
    ("MSIB XXV Issue: 048 High Water Safety Advisory: VTS Safety Measure at LMR MM 170 TO MM 237", "closure_or_river_stage"),
    ("MSIB Vol XXI, Issue 036- Carrollton Gauge 12 Feet and Falling", "closure_or_river_stage"),
    ("SEC VA MSIB 001-25 Deep Creek Bridge Deviation", "closure_or_river_stage"),
    ("VTS Houston-Galveston - Vessel Tracking System Restored", "closure_or_river_stage"),
    ("CAT I Closure - Roll on/Roll off Operations in Carpenter's Bayou - 30SEP26 - 1300 - 1700", "closure_or_river_stage"),
    ("Coast Guard to set Port Condition YANKEE for 2 seaports in the U.S. Virgin Islands", "storm_or_port_condition"),
    ("GPS OPERATIONAL ADVISORY JDAY 273", "navigation_warning"),
    ("New NANU 2026080", "navigation_warning"),
    ("Iceberg Products at 0000Z on 30 SEP 2026", "navigation_warning"),
    ("MSIB Vol XXV Issue 055 New Orleans Grand Prix", "marine_event"),
    ("MSIB 07-20 Ports and Facilities MSIB for Coranavirus", "pandemic_measures"),
    ("ALCOAST 316/26 - SEP 2026 VOTER REGISTRATION AND ELECTION PARTICIPATION", "internal_notice"),
    ("ACN 026/18 - MAR 2018 COLOR VISION TESTING", "internal_notice"),
])
def test_dropped(subject, kind):
    assert b.drop_reason(subject) == kind


@pytest.mark.parametrize("subject", [
    "ALCOAST 414/24 - NOV 2024 USE OF FOUR DIGIT VHF-FM WORKING CHANNELS NUMBERS",
    "ACN 013/18 - FEB 2018 ENFORCEMENT, EXAMINATION, AND INSPECTION PROCEDURES FOR KIDDE FIRE EXTINGUISHER RECALL",
    "MSIB XVIII Issue 069 Special Consideration for ITV Flammable Storage Cabinets",
    "(Correction) MSIB Vol XXIII Issue 012 Notification of Marine Casualty and Hazardous Condition",
    "New Merchant Mariner Credential (MMC)",
    "Amendments to STCW Basic Training Requirements  for Personal Safety and Social Responsibilities",
])
def test_kept(subject):
    assert b.drop_reason(subject) is None


def test_verdicts():
    d = date(2026, 9, 29)
    assert b.subject_verdict("MSIB XXV Issue: 048 High Water Safety Advisory", d, "abc1234") == \
        ("drop", "closure_or_river_stage")                       # drop wins over Pass 1
    assert b.subject_verdict("MSIB XVIII Issue 069 Special Consideration for ITV Flammable Storage Cabinets",
                             d, "abc1234") == ("accept", ("MSIB Vol XVIII Issue 069", "MSIB"))
    assert b.subject_verdict("Amendments to STCW Basic Training Requirements", d, "42d27dfab") == \
        ("accept", ("USCG REGULATORY 2026-09-29 [42d27df]", "KEYWORD_REGULATORY"))
    assert b.subject_verdict("News Release: Coast Guard issues safety alert", d, "x")[0] == "deny"
    assert b.subject_verdict("Introducing the New NAVCEN Maritime Safety Information Application!",
                             d, "x") == ("ambiguous", None)


def test_alias_tail():
    t = "MSIB Vol XXV Issue 001 Maritime security (port security, MARSEC, security zone, port closure)"
    assert b.strip_alias_tail(t) == "MSIB Vol XXV Issue 001 Maritime security"
    assert b.strip_alias_tail("Rule 9 (Narrow Channels)") == "Rule 9 (Narrow Channels)"


FEED = """<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel><title>USCG</title>
<item><pubDate>Tue, 29 Sep 2026 23:07:49 -0500</pubDate><title>Elevated Winds - Houston Ship Channel</title>
<link>https://content.govdelivery.com/accounts/USDHSCG/bulletins/42d294d</link></item>
<item><pubDate>Tue, 29 Sep 2026 20:00:00 -0500</pubDate><title>Amendments to STCW Basic Training Requirements</title>
<link>https://content.govdelivery.com/accounts/USDHSCG/bulletins/42d27df</link></item>
<item><pubDate>Tue, 29 Sep 2026 19:00:00 -0500</pubDate><title>Introducing the New NAVCEN App &amp; More</title>
<link>https://content.govdelivery.com/accounts/USDHSCG/bulletins/42d2000</link></item>
<item><pubDate>Mon, 28 Sep 2026 10:00:00 -0500</pubDate><title>New Merchant Mariner Credential</title>
<link>https://content.govdelivery.com/accounts/USDHSCG/bulletins/41aaaaa</link></item>
</channel></rss>"""

PAGE = """<html><head><title>x</title></head><body>
<h1 class='bulletin_subject'>Amendments to STCW Basic Training Requirements</h1>
<span class='dateline'>09/29/2026 08:00 PM CDT</span>
<div class='bulletin_body'><p>The Coast Guard announces amendments to 46 CFR 12.602 basic training.</p></div>
</body></html>"""


def test_feed_xml():
    items = b.parse_feed_xml(FEED)
    assert [i.gd_id for i in items] == ["42d294d", "42d27df", "42d2000", "41aaaaa"]
    assert items[0].published_date == date(2026, 9, 29) and items[2].subject == "Introducing the New NAVCEN App & More"


def test_parse_feed_fetches_only_new_accepted_items(tmp_path, monkeypatch):
    ids_file = tmp_path / "wayback_ids.txt"
    ids_file.write_text("41aaaaa\n")                      # decided by an earlier run

    class Resp:
        text = FEED

        def raise_for_status(self):
            return None

    fetched = []

    async def fake_fetch(client, gd_id):
        fetched.append(gd_id)
        return PAGE, 200

    monkeypatch.setattr(b.httpx, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(b, "_fetch_bulletin_html", fake_fetch)
    monkeypatch.delenv("USCG_BULLETIN_LLM", raising=False)
    sections = b.parse_feed(ids_file)
    assert fetched == ["42d27df"]
    assert [s.section_number for s in sections] == ["USCG REGULATORY 2026-09-29 [42d27df]"]
    assert "content.govdelivery.com/accounts/USDHSCG/bulletins/42d27df" in sections[0].full_text
    assert ids_file.read_text().split() == ["41aaaaa", "42d27df"]
    assert (tmp_path / b.FEED_SEEN).read_text().split() == ["42d294d", "42d27df", "42d2000"]
    assert "42d2000" in (tmp_path / b.FEED_REVIEW).read_text()
    # a second run finds nothing new
    fetched.clear()
    assert b.parse_feed(ids_file) == [] and fetched == []


def test_prune_plan_drops_ephemeral_rows_and_second_copies():
    docs = [
        {"section_number": "MSIB Vol XXV Issue 046", "section_title": "MSIB Vol XXV Issue 046 LMR 170 - 237, 38'and Falling", "gd_id": "3e00093"},
        {"section_number": "USCG POLICY_LETTER 2017-06-14 [1a25ee8]", "section_title": "Third Party Awareness", "gd_id": "1a25ee8"},
        {"section_number": "USCG OTHER_REGULATORY 2017-06-14 [1a25ee8]", "section_title": "Third Party Awareness", "gd_id": "1a25ee8"},
        {"section_number": "NMC Announcement 2024-02-26", "section_title": "New Merchant Mariner Credential (MMC)", "gd_id": "38a10a5f1"},
        {"section_number": "USCG NMC 2024-02-26 [38a10a5]", "section_title": "New Merchant Mariner Credential (MMC)", "gd_id": "38a10a5"},
    ]
    plan = b.prune_plan(docs)
    assert plan == {
        "MSIB Vol XXV Issue 046": "closure_or_river_stage",
        "USCG OTHER_REGULATORY 2017-06-14 [1a25ee8]": "duplicate of USCG POLICY_LETTER 2017-06-14 [1a25ee8]",
        "USCG NMC 2024-02-26 [38a10a5]": "duplicate of NMC Announcement 2024-02-26",
    }


def test_stale_report_counts_kept_rows_as_produced():
    class Pool:
        async def fetch(self, sql, source):
            assert source == "uscg_bulletin"
            return [
                {"id": "00000000-0000-0000-0000-000000000001", "section_number": "GPS X", "section_title": "GPS OPERATIONAL ADVISORY JDAY 083",
                 "chunk_index": 0, "head": "Source URL: https://content.govdelivery.com/accounts/USDHSCG/bulletins/aa11", "created": "2026-04-19"},
                {"id": "00000000-0000-0000-0000-000000000002", "section_number": "NMC Announcement 2024-02-27", "section_title": "New Merchant Mariner Credential",
                 "chunk_index": 0, "head": "Source URL: https://content.govdelivery.com/accounts/USDHSCG/bulletins/bb22", "created": "2026-04-19"},
            ]

    report = asyncio.run(b.stale_report(Pool()))
    assert report.stored == 2 and report.produced == 1
    assert [(r["section_number"], r["reason"]) for r in report.stale] == [("GPS X", "navigation_warning")]
    assert report.safe

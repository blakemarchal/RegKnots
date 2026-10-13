"""2026-10-13 — IMO harvester, answer side: the dates block and today's date
behind IMO_DATES_PROMPT_ENABLED, every IMO source in a retrieval group, the
binding IMO instruments at Tier 1, MEPC / Assembly numbers in the verifier."""
import re

from rag import engine as E
from rag.authority import tier_for_source
from rag.prompts import DATES_AND_AMENDMENTS_BLOCK, assemble_system_prompt
from rag.retriever import SOURCE_GROUPS, _SOURCE_TO_GROUP


def test_dates_block_only_with_the_flag_in_every_mode():
    assert DATES_AND_AMENDMENTS_BLOCK not in assemble_system_prompt()
    assert DATES_AND_AMENDMENTS_BLOCK not in assemble_system_prompt(provenance=True)
    for kwargs in ({}, {"provenance": True}, {"model_led": True}, {"precision_mode": True}):
        assert DATES_AND_AMENDMENTS_BLOCK in assemble_system_prompt(dates=True, **kwargs)


def test_today_line_in_the_user_turn_only_with_the_flag():
    plain = E._build_chat_messages("When does VDES apply?", [], None, "ctx")[-1]["content"]
    dated = E._build_chat_messages("When does VDES apply?", [], None, "ctx", today=True)[-1]["content"]
    assert "Today's date" not in plain
    assert re.search(r"Today's date: \d{1,2} [A-Z][a-z]+ \d{4}\.", dated)
    assert dated.replace(E.today_line() + "\n\n", "") == plain


def test_every_imo_source_is_in_a_retrieval_group():
    for src in ("imo_igf", "imo_polar", "imo_symbols", "marpol_amend", "imo_bwm", "stcw_amend",
                "imo_msc", "imo_mepc", "imo_lsa", "imo_fss"):
        assert src in _SOURCE_TO_GROUP, src
    assert _SOURCE_TO_GROUP["marpol_amend"] == "marpol"
    assert _SOURCE_TO_GROUP["stcw_amend"] == "stcw"
    assert _SOURCE_TO_GROUP["imo_igf"] == "imo_codes"
    # one group per source
    seen = [s for srcs in SOURCE_GROUPS.values() for s in srcs]
    assert len(seen) == len(set(seen))


def test_binding_imo_instruments_are_tier_1():
    for src in ("marpol", "marpol_amend", "imdg", "mlc", "stcw_amend", "imo_lsa", "imo_fss",
                "imo_igf", "imo_polar", "imo_bwm"):
        assert tier_for_source(src) == 1, src
    assert tier_for_source("imo_msc") == 2 and tier_for_source("imo_mepc") == 2


def test_verifier_reads_mepc_and_assembly_numbers():
    text = "See MSC.583(111), MEPC.400(83) and A.1206(34); Part A.1 is not one."
    assert [m.group(0) for m in E._MSC_RE.finditer(text)] == ["MSC.583(111)"]
    assert [m.group(0) for m in E._MEPC_RE.finditer(text)] == ["MEPC.400(83)"]
    assert [m.group(0) for m in E._ASSEMBLY_RE.finditer(text)] == ["A.1206(34)"]


def test_what_is_coming_questions_get_the_calendar():
    from rag.live_context import detect_live_context
    for q in ("Which IMO amendments enter into force on 1 January 2026?",
              "What upcoming amendments affect container ships?",
              "When do the VDES rules come into force?",
              "What's changing for tankers next year?"):
        assert detect_live_context(q) == "reg_changes", q
    assert detect_live_context("How many fire extinguishers does my towboat need?") is None


def test_reg_changes_block_lists_upcoming_imo_amendments():
    import asyncio
    from datetime import date

    from rag.live_context import build_reg_changes_block

    class Pool:
        async def fetch(self, sql, *args):
            if "CURRENT_DATE + 548" in sql:
                return [{"code": "MSC.583(111)", "published_date": date(2028, 1, 1),
                         "section_title": "IMO MSC Resolution MSC.583(111) — Amendments to SOLAS IV and V"},
                        {"code": "MEPC.400(83)", "published_date": date(2027, 1, 1),
                         "section_title": "IMO MEPC Resolution MEPC.400(83) — CII reduction factors"}]
            return []

    block = asyncio.run(build_reg_changes_block(Pool(), "what is coming into force?"))
    assert block.startswith("IMO AMENDMENTS ENTERING INTO FORCE")
    assert block.index("MEPC.400(83)") < block.index("MSC.583(111)")      # soonest first
    assert "in force 2028-01-01" in block
    assert "No sections were added or updated" in block

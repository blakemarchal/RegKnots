"""2026-09-26 — hedge-judge recovery gate, post-done analytics, credential instruction.

The D6.97 Phase 1a gate read `verified_cited` (every retrieved section that
exists in the DB) as "the answer has verified citations", so the citation
oracle and web fallback never fired. See docs/sprint-audits/question-audit-2026-09-25.md §3.7.
"""
import asyncio
import json

import pytest

import rag.engine as E

CITED = "Weekly and monthly inspections are required (SOLAS Ch.III Reg.20)."
UNCITED = "I could not find the inspection intervals in the retrieved context."


@pytest.mark.parametrize("verdict,topic,answer,oracle,web,query", [
    # partial miss that names what is missing: corpus oracle even with citations, no web card
    ("partial_miss", "Reg.20 weekly and monthly inspections", CITED, True, False,
     "Reg.20 weekly and monthly inspections"),
    # a miss with no citation in the answer: oracle first, then the web card
    ("complete_miss", None, UNCITED, True, True, None),
    ("partial_miss", "falls renewal", UNCITED, True, True, "falls renewal"),
    # a cited answer keeps the Phase 1a trust contract
    ("complete_miss", None, CITED, False, False, None),
    ("partial_miss", None, CITED, False, False, None),
    # not a miss
    ("precision_callout", None, UNCITED, False, False, None),
    (None, None, UNCITED, False, False, None),
])
def test_recovery_plan(verdict, topic, answer, oracle, web, query):
    plan = E._recovery_plan(judge_verdict=verdict, judge_missing_topic=topic, answer=answer,
                            citation_oracle_enabled=True)
    assert (plan.run_oracle, plan.run_web, plan.oracle_query) == (oracle, web, query)


def test_oracle_disabled_leaves_the_web_card():
    plan = E._recovery_plan(judge_verdict="complete_miss", judge_missing_topic=None, answer=UNCITED,
                            citation_oracle_enabled=False)
    assert (plan.run_oracle, plan.run_web) == (False, True)


def test_a_named_retrieved_section_counts_as_a_citation():
    # The regex extractor doesn't know MARPOL; the UI footer counts named context sections.
    answer = "Log it in the Oil Record Book per MARPOL Annex I Reg.17."
    base = dict(judge_verdict="complete_miss", judge_missing_topic=None, answer=answer,
                citation_oracle_enabled=True)
    assert E._recovery_plan(**base).run_web is True
    plan = E._recovery_plan(**base, context_sections=["MARPOL Annex I Reg.17", "46 CFR 199.180"])
    assert plan.has_text_citations and not plan.run_web and plan.text_citation_count == 1


def test_background_tasks_finish_after_the_caller_and_swallow_errors():
    done = []

    async def slow_ok():
        await asyncio.sleep(0.01)
        done.append("ok")

    async def boom():
        raise RuntimeError("judge exploded")

    async def run():
        E._spawn_background(slow_ok(), "t1")
        E._spawn_background(boom(), "t2")
        assert len(E._BACKGROUND_TASKS) == 2           # strong refs held
        await asyncio.sleep(0.05)
        return len(E._BACKGROUND_TASKS)

    assert asyncio.run(run()) == 0 and done == ["ok"]


def test_credential_block_only_for_credential_questions():
    msgs = E._build_chat_messages(
        query="What is a bunker CLC?", conversation_history=[], vessel_profile=None,
        context_str="[SOURCE: SOLAS Annex 1]", credential_context="MARINER CREDENTIALS ON FILE:\n- MEDICAL: x — EXPIRED 40 days ago",
    )
    text = json.dumps(msgs)
    assert "only when the question is about the user" in text
    assert "Do not add reminders about the user's certificates" in text
    assert "When relevant, tailor your answer" not in text

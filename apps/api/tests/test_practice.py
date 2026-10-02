"""2026-10-02 — the public exam-practice endpoints."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from app.routers import practice


class Pool:
    def __init__(self, rows):
        self.rows = rows
        self.starts = []

    async def fetch(self, sql, *args):
        self.last = (sql, args)
        return self.rows

    async def execute(self, sql, topic):
        self.starts.append(topic)


def q(i, sim=0.7, choices=None):
    return {"id": i, "pool": "Q101", "part": "Deck General – Part I", "exam": "Master/Chief Mate of Unlimited Tonnage",
            "topic_label": "Deck General Knowledge", "stem": f"Question {i}?",
            "choices": json.dumps(choices or {"A": "a", "B": "b", "C": "c", "D": "d"}), "answer": "C",
            "related_source": "cfr_46", "related_section": "46 CFR 10.201", "related_title": "Eligibility",
            "related_similarity": sim}


def test_quiz_serves_answers_and_only_close_related_sections():
    pool = Pool([q(1), q(2, sim=0.41)])
    out = asyncio.run(practice.quiz(topic="deck_general", n=10, exam=None, pool=pool))
    assert [x["id"] for x in out["questions"]] == [1, 2]
    assert out["questions"][0]["choices"]["C"] == "c" and out["questions"][0]["answer"] == "C"
    assert out["questions"][0]["related"]["section"] == "46 CFR 10.201"
    assert out["questions"][1]["related"] is None                 # under the similarity floor
    assert pool.starts == ["deck_general"]
    assert "NOT needs_figure" in pool.last[0] and pool.last[1] == ("deck_general", 10, None)


def test_unknown_topic_is_404_and_not_counted():
    pool = Pool([])
    with pytest.raises(HTTPException) as exc:
        asyncio.run(practice.quiz(topic="nope", n=10, exam=None, pool=pool))
    assert exc.value.status_code == 404 and pool.starts == []


def test_topics_group_and_order_with_exam_levels():
    def row(key, label, exam, n, total=0):
        return {"topic_key": key, "topic_label": label, "exam": exam, "n": n, "is_total": total}

    rows = [
        row("engine_motor", "Engine — Motor Plants", "QMED", 40),
        row("engine_motor", "Engine — Motor Plants", None, 40, total=1),
        row("rules_of_road", "Rules of the Road (COLREGs)", "Deck Officer Endorsements", 42),
        row("rules_of_road", "Rules of the Road (COLREGs)", None, 42, total=1),
        row("deck_general", "Deck General Knowledge", "OUPV", 30),
        row("deck_general", "Deck General Knowledge", "Master 100 GRT", 55),
        # 10 questions are in both exams: the topic total counts them once
        row("deck_general", "Deck General Knowledge", None, 75, total=1),
    ]
    pool = Pool(rows)
    out = asyncio.run(practice.topics(pool=pool))
    assert [t["key"] for t in out["topics"]] == ["rules_of_road", "deck_general", "engine_motor"]
    deck = out["topics"][1]
    assert deck["group"] == "Deck" and deck["count"] == 75
    assert [e["exam"] for e in deck["exams"]] == ["Master 100 GRT", "OUPV"]
    assert out["total"] == 157
    assert "count(DISTINCT stem" in pool.last[0] and "GROUPING SETS" in pool.last[0]


def test_quiz_serves_a_repeated_question_once():
    pool = Pool([q(1)])
    asyncio.run(practice.quiz(topic="deck_general", n=10, exam="OUPV", pool=pool))
    assert "DISTINCT ON (stem, choices)" in pool.last[0] and pool.last[1] == ("deck_general", 10, "OUPV")

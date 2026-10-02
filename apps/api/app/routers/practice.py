"""Free USCG exam practice (2026-10-02). Public, no login.

Serves the NMC sample-examination questions (exam_questions, loaded by
packages/ingest/ingest/exam_questions.py) to the /practice page: the official
questions with their answer keys, public domain. Questions that need an
illustration, a table or a reference book (needs_figure) are not served.

Each question carries its nearest corpus section when that match is close
enough (RELATED_MIN_SIMILARITY), so practice points at the rule behind the
answer at no per-view cost. Every quiz served adds one practice_quiz_starts
row (topic only: no user, no IP) so the page can be measured.

The same question is printed in more than one sample exam, so counts and
quizzes treat a stem with the same choices as one question.
"""
from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/practice", tags=["practice"])

# Below this the nearest section is often only topically related.
RELATED_MIN_SIMILARITY = 0.55

# The page's three columns; topic keys from ingest/sources/nmc_exam_bank.py.
_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("Deck", ("rules_of_road", "deck_general", "deck_safety", "nav_general", "nav_problems",
              "nav_deck_general", "deck_stability", "great_lakes", "assistance_towing", "auxiliary_sail")),
    ("Engine", ("engine_general", "engine_motor", "engine_steam", "engine_gas_turbine", "engine_electrical",
                "engine_safety_env", "qmed")),
    ("Endorsements", ("lifeboatman", "tankship_dangerous", "tankship_gases", "barge_supervisor", "bco", "oim")),
]
_GROUP_OF = {key: group for group, keys in _GROUPS for key in keys}


@router.get("/topics")
async def topics(pool=Depends(get_pool)) -> dict[str, Any]:
    """Servable topics with question counts and the exam levels under each."""
    # One row per (topic, exam) plus a topic total (is_total), each counting
    # distinct questions: a question shared by two exams counts once in the total.
    rows = await pool.fetch(
        """
        SELECT topic_key, topic_label, exam, GROUPING(exam) AS is_total,
               count(DISTINCT stem || choices::text) AS n
        FROM exam_questions WHERE NOT needs_figure
        GROUP BY GROUPING SETS ((topic_key, topic_label, exam), (topic_key, topic_label))
        """
    )
    by_topic: dict[str, dict[str, Any]] = {}
    for r in rows:
        t = by_topic.setdefault(r["topic_key"], {"key": r["topic_key"], "label": r["topic_label"],
                                                 "group": _GROUP_OF.get(r["topic_key"], "Endorsements"),
                                                 "count": 0, "exams": []})
        if r["is_total"]:
            t["count"] = r["n"]
        elif r["exam"]:
            t["exams"].append({"exam": r["exam"], "count": r["n"]})
    for t in by_topic.values():
        t["exams"].sort(key=lambda e: -e["count"])
    order = {key: i for i, key in enumerate(k for _, keys in _GROUPS for k in keys)}
    listed = sorted(by_topic.values(), key=lambda t: (order.get(t["key"], 99), t["label"]))
    return {"topics": listed, "total": sum(t["count"] for t in listed),
            "groups": [g for g, _ in _GROUPS]}


@router.get("/quiz")
async def quiz(
    topic: Annotated[str, Query(max_length=40)],
    n: Annotated[int, Query(ge=1, le=25)] = 10,
    exam: Annotated[str | None, Query(max_length=120)] = None,
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """n random servable questions from a topic (and exam level, if given)."""
    rows = await pool.fetch(
        """
        SELECT * FROM (
            SELECT DISTINCT ON (stem, choices)
                   id, pool, part, exam, topic_label, stem, choices, answer,
                   related_source, related_section, related_title, related_similarity
            FROM exam_questions
            WHERE topic_key = $1 AND NOT needs_figure AND ($3::text IS NULL OR exam = $3)
            ORDER BY stem, choices, random()
        ) q
        ORDER BY random()
        LIMIT $2
        """,
        topic, n, exam,
    )
    if not rows:
        raise HTTPException(status_code=404, detail="No practice questions for that topic.")
    try:
        await pool.execute("INSERT INTO practice_quiz_starts (topic_key) VALUES ($1)", topic)
    except Exception:  # measuring never blocks the quiz
        logger.exception("practice: could not record a quiz start")
    questions = []
    for r in rows:
        choices = r["choices"] if isinstance(r["choices"], dict) else json.loads(r["choices"])
        related = None
        if r["related_section"] and (r["related_similarity"] or 0) >= RELATED_MIN_SIMILARITY:
            related = {"source": r["related_source"], "section": r["related_section"],
                       "title": r["related_title"]}
        questions.append({"id": r["id"], "pool": r["pool"], "part": r["part"], "exam": r["exam"],
                          "stem": r["stem"], "choices": choices, "answer": r["answer"], "related": related})
    return {"topic": topic, "label": rows[0]["topic_label"], "questions": questions}

"""Study Tools router — Sprint D6.83 Phase A2.

Endpoints:

  POST /study/quiz                            — generate 10-question quiz (Haiku)
  POST /study/guide                           — generate study guide (Haiku, Sonnet on deep_dive)
  GET  /study/library                         — list user's saved generations
  GET  /study/library/{id}                    — fetch single generation
  POST /study/library/{id}/archive            — soft-archive
  POST /study/library/{id}/unarchive
  POST /study/quiz-sessions                   — start a take-the-quiz session
  POST /study/quiz-sessions/{id}/answer       — submit one answer
  POST /study/quiz-sessions/{id}/finish       — finalize + grade
  GET  /study/quiz-sessions/{id}              — fetch session state (resume)
  GET  /study/usage                           — current month generation count + cap

Generation cap (D6.83):
  - Mate     : 200 generations/month (computed from study_generations)
  - Captain  : unlimited
  - Free     : study tools require paid tier — return 402

Model routing:
  - Quizzes : ALWAYS Haiku 4.5. Structured-output friendly + cheap.
  - Guides  : Haiku 4.5 by default; Sonnet 4.6 only when deep_dive=True.

Retrieval:
  - Quizzes pull from nmc_exam_bank (the curated USCG exam-pool ingest)
    AND from chat-corpus (CFR/SOLAS/etc.) so answer keys can cite real
    regulation text.
  - Guides pull primarily from chat-corpus regulations; exam_bank
    surfaces "what's commonly tested" framing.
"""
from __future__ import annotations

import json
import logging
import random
import re
import uuid as _uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Optional

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/study", tags=["study"])


# ── Constants ──────────────────────────────────────────────────────────────

# Model choices. Quizzes are always Haiku — structured-output, cheap,
# and the ground truth is the regulation citation, not the model's
# reasoning depth. Guides default Haiku for cost, Sonnet on deep_dive.
_QUIZ_MODEL = "claude-haiku-4-5-20251001"
_GUIDE_MODEL_FAST = "claude-haiku-4-5-20251001"
_GUIDE_MODEL_DEEP = "claude-sonnet-4-6"

# Per-month generation caps by tier. Captain is unlimited (None).
_MATE_STUDY_CAP_PER_MONTH = 200
_CAPTAIN_STUDY_CAP_PER_MONTH = None

# Token budgets — quizzes are dense (10 questions × 4 options × short
# explanation), guides are denser still. Plenty of headroom; we'd
# rather pay a few cents than truncate.
_QUIZ_MAX_TOKENS = 4000
_GUIDE_MAX_TOKENS_FAST = 4000
_GUIDE_MAX_TOKENS_DEEP = 8000


# ── Prompts ────────────────────────────────────────────────────────────────

_QUIZ_SYSTEM_PROMPT = """You are RegKnots' Study Tools quiz writer for USCG mariner exam prep. You generate authentic, exam-style multiple-choice questions anchored on real regulations.

Hard rules:
1. Generate exactly 10 questions on the user's topic.
2. Each question MUST have exactly 4 options (A / B / C / D), one correct.
3. Each correct answer MUST cite a specific regulation section from the supplied corpus passages (e.g. "46 CFR 199.190" or "COLREGs Rule 13"). Never invent a section.
4. Each question MUST include a 1-3 sentence explanation of why the correct answer is right, anchored to the cited regulation.
5. Mix difficulty: 3 easy (single fact recall), 5 medium (apply the rule), 2 hard (cross-reference or conditional).
6. Question stems should mirror USCG exam style: vessel-scenario framing where natural ("A 95-foot small passenger vessel operating coastwise…"), direct-question framing otherwise.
7. Distractors (the 3 wrong options) must be plausible — common confusions, near-but-wrong values, related-but-different regulations. Never use throwaway options like "all of the above" or joke answers.

Output JSON only — no prose, no markdown fences:

{
  "title": "≤80-char descriptive title",
  "topic": "the user's submitted topic, normalized",
  "questions": [
    {
      "stem": "question text",
      "options": {"A": "...", "B": "...", "C": "...", "D": "..."},
      "correct_letter": "A" | "B" | "C" | "D",
      "explanation": "1-3 sentences anchored on the cited regulation",
      "citation": "46 CFR 199.190" | "COLREGs Rule 13" | etc.,
      "difficulty": "easy" | "medium" | "hard"
    }
    ... 10 total
  ]
}
"""

_GUIDE_SYSTEM_PROMPT = """You are RegKnots' Study Tools guide writer for USCG mariner exam prep. You write focused study guides anchored on real regulations.

Hard rules:
1. Output a structured guide on the user's topic, organized into 4-7 logical sections.
2. Each section MUST include at least one citation to a specific regulation section from the supplied corpus passages (e.g. "46 CFR 199.190" or "SOLAS Ch.III Reg.19"). Never invent.
3. Lead with what the mariner needs to KNOW (the rule), then HOW IT APPLIES (real-world scenario), then COMMON EXAM TRAPS (the distinctions exam writers test).
4. Length: ~600-1200 words for fast (Haiku), ~1500-2500 words for deep (Sonnet). Quality over verbosity.
5. End with a "Key Citations" section listing every regulation referenced, in citation order.

Output JSON only — no prose, no markdown fences:

{
  "title": "≤80-char descriptive title",
  "topic": "user's submitted topic, normalized",
  "sections": [
    {
      "heading": "Section title",
      "content_md": "Markdown body — paragraphs, bullet lists, bold key terms",
      "citations": ["46 CFR 199.190", "SOLAS Ch.III Reg.19"]
    }
    ... 4-7 total
  ],
  "key_citations": ["46 CFR 199.190", "SOLAS Ch.III Reg.19", ...]
}
"""


# ── Pydantic models ────────────────────────────────────────────────────────


class QuizGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=300)
    # Optional vessel context — guides retrieval if the topic
    # would otherwise be ambiguous across vessel types.
    vessel_id: Optional[str] = None


class GuideGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=300)
    deep_dive: bool = False         # True → Sonnet, False → Haiku
    vessel_id: Optional[str] = None


class GenerationSummary(BaseModel):
    """Lightweight summary used in /study/library list response."""
    id: str
    kind: str                       # 'quiz' | 'guide'
    title: str
    topic: str
    topic_key: Optional[str]
    model_used: str
    created_at: str
    archived_at: Optional[str]


class GenerationDetail(BaseModel):
    """Full generation including the structured content payload."""
    id: str
    kind: str
    title: str
    topic: str
    topic_key: Optional[str]
    content_json: dict[str, Any]
    model_used: str
    created_at: str
    archived_at: Optional[str]


class QuizSessionStartRequest(BaseModel):
    generation_id: str


class QuizSessionAnswerRequest(BaseModel):
    q_index: int = Field(..., ge=0, lt=50)        # bounded; we only generate 10
    selected_letter: str = Field(..., pattern=r"^[A-D]$")


class QuizSessionAnswer(BaseModel):
    q: int
    selected: str
    correct_letter: str
    is_correct: bool
    answered_at: str


class QuizSessionDetail(BaseModel):
    id: str
    generation_id: str
    answers: list[QuizSessionAnswer]
    score_pct: Optional[float]
    started_at: str
    finished_at: Optional[str]
    elapsed_seconds: Optional[int]


class UsageDTO(BaseModel):
    tier: str
    used_this_month: int
    cap: Optional[int]              # None = unlimited
    can_generate: bool


# ── Helpers ────────────────────────────────────────────────────────────────


async def _fetch_user_tier(pool, user_uuid: _uuid.UUID) -> tuple[str, bool]:
    """Returns (subscription_tier, is_privileged).

    is_privileged includes admin / internal users — they bypass caps."""
    row = await pool.fetchrow(
        "SELECT subscription_tier, is_admin, is_internal FROM users WHERE id = $1",
        user_uuid,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    is_priv = bool(row["is_admin"]) or bool(row.get("is_internal"))
    return row["subscription_tier"] or "free", is_priv


async def _check_cap(pool, user_uuid: _uuid.UUID) -> tuple[int, Optional[int]]:
    """Returns (used_this_month, cap). Raises 402 when at/over cap.

    Free tier (no Mate / no Captain) returns 402 immediately — study
    tools are paid-tier features.
    """
    tier, is_priv = await _fetch_user_tier(pool, user_uuid)

    if is_priv:
        return 0, None

    if tier not in ("mate", "captain"):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                "Study Tools require a Mate or Captain subscription. "
                "Subscribe to unlock quiz + study guide generators."
            ),
        )

    cap = _MATE_STUDY_CAP_PER_MONTH if tier == "mate" else _CAPTAIN_STUDY_CAP_PER_MONTH

    used = int(await pool.fetchval(
        """
        SELECT COUNT(*) FROM study_generations
        WHERE user_id = $1 AND created_at >= date_trunc('month', NOW())
        """,
        user_uuid,
    ) or 0)

    if cap is not None and used >= cap:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Mate plan monthly Study Tools cap reached ({cap} generations). "
                "Upgrade to Captain for unlimited study tool generations, or "
                "wait until next month."
            ),
        )
    return used, cap


async def _retrieve_for_topic(
    topic: str,
    *,
    include_exam_bank: bool = True,
    k_exam_bank: int = 4,
    k_corpus: int = 6,
) -> tuple[list[dict], list[dict]]:
    """Retrieve (exam_bank_chunks, corpus_chunks) for a topic.

    exam_bank_chunks come from the nmc_exam_bank source explicitly —
    chat retrieval ignores them, but we want them for quiz/guide
    generation as "what's tested" context.

    corpus_chunks come from the regular chat retrieval pipeline so
    we get the same source-affinity boosts, multi-query rewrite,
    reranking — anything that improves chat answer quality also
    improves study tool quality.
    """
    from app.config import settings
    from rag.retriever import retrieve

    pool = await get_pool()
    exam_chunks: list[dict] = []
    corpus_chunks: list[dict] = []

    if include_exam_bank:
        # Direct SQL — chat retrieval explicitly excludes nmc_exam_bank
        # from SOURCE_GROUPS, so we bypass it for this targeted pull.
        # ILIKE on section_title for topic match (titles are like
        # "Deck Safety — USCG exam-pool questions (Q103)").
        try:
            rows = await pool.fetch(
                """
                SELECT id, source, section_number, section_title, full_text,
                       1.0 AS similarity
                FROM regulations
                WHERE source = 'nmc_exam_bank'
                  AND (section_title ILIKE '%' || $1 || '%'
                       OR full_text ILIKE '%' || $1 || '%')
                ORDER BY length(full_text) DESC
                LIMIT $2
                """,
                topic, k_exam_bank,
            )
            exam_chunks = [dict(r) for r in rows]
        except Exception as exc:
            logger.warning(
                "exam_bank retrieval failed (degrading to corpus-only): %s: %s",
                type(exc).__name__, str(exc)[:200],
            )

    try:
        corpus_chunks = await retrieve(
            query=topic,
            pool=pool,
            openai_api_key=settings.openai_api_key,
            limit=k_corpus,
        )
    except Exception as exc:
        logger.warning(
            "corpus retrieval failed: %s: %s",
            type(exc).__name__, str(exc)[:200],
        )

    return exam_chunks or [], corpus_chunks or []


def _format_chunks_for_prompt(
    exam_chunks: list[dict], corpus_chunks: list[dict],
) -> str:
    """Format both chunk sources into a single context block for the LLM."""
    parts: list[str] = []
    if exam_chunks:
        parts.append("=== USCG EXAM POOL CONTENT (style + topic reference) ===")
        for c in exam_chunks:
            parts.append(
                f"\n[{c.get('section_number')}] {c.get('section_title') or ''}\n"
                f"{(c.get('full_text') or '')[:1500]}"
            )
    if corpus_chunks:
        parts.append("\n\n=== REGULATION CORPUS (cite from these) ===")
        for c in corpus_chunks:
            parts.append(
                f"\n[{c.get('section_number')}] {c.get('section_title') or ''}\n"
                f"{(c.get('full_text') or '')[:1500]}"
            )
    return "\n".join(parts)


def _parse_json_response(text: str) -> Optional[dict]:
    """Tolerant JSON parser — strip markdown fences if present, then
    fall back to first {...} block extraction."""
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


# ── Citation verification ──────────────────────────────────────────────────


# Match the leading "base" portion of a citation, stripping any
# subsection parenthetical. Examples:
#   "46 CFR 199.45(a)(1)"  → "46 CFR 199.45"
#   "COLREGs Rule 13"      → "COLREGs Rule 13"
#   "SOLAS Ch.III Reg.19"  → "SOLAS Ch.III Reg.19"
# The corpus stores section_number at the base level; cited subsections
# from the model don't appear verbatim in DB, so we match on the base.
_CITATION_BASE_RE = re.compile(r"^([^(]+)")


def _citation_base(cite: str) -> str:
    """Strip subsection parentheticals from a citation. Returns the
    portion the corpus indexes at section_number granularity."""
    if not cite:
        return ""
    m = _CITATION_BASE_RE.match(cite.strip())
    return (m.group(1) if m else cite).strip()


async def _verify_citations(pool, citations: list[str]) -> dict[str, bool]:
    """Given a list of citation strings, return {citation: True/False}
    indicating whether each citation's base section number resolves to
    a real entry in the regulations corpus.

    This is the same quality moat the chat product uses — every cited
    section must exist in the corpus, otherwise it's potentially a
    Haiku hallucination. We don't BLOCK generation on a bad citation
    (would frustrate users when one of ten missed); we surface the
    rate to the frontend so users see a verification confidence."""
    if not citations:
        return {}
    bases = list({_citation_base(c) for c in citations if c})
    if not bases:
        return {c: False for c in citations}
    rows = await pool.fetch(
        "SELECT DISTINCT section_number FROM regulations "
        "WHERE section_number = ANY($1::text[])",
        bases,
    )
    verified_bases: set[str] = {r["section_number"] for r in rows}
    return {
        c: _citation_base(c) in verified_bases
        for c in citations
    }


# ── Option shuffling (Haiku positional-bias fix) ──────────────────────────


_LETTERS: tuple[str, str, str, str] = ("A", "B", "C", "D")


def _shuffle_question_options(question: dict) -> None:
    """Randomly permute the (A,B,C,D) options of a single question and
    remap `correct_letter` to follow the correct text into its new slot.

    Why this exists: Haiku (and other small instruction-tuned models)
    have measurable positional bias — they cluster correct answers in
    the middle slots (B/C) and rarely place them at A or D. Asking the
    model to "balance the distribution" via prompt is unreliable. We
    fix it server-side by shuffling each question independently.

    Mutates the question dict in place.
    """
    opts = question.get("options") or {}
    correct_old = question.get("correct_letter")
    if not correct_old or correct_old not in _LETTERS:
        return  # malformed question — leave it alone for the parser to handle

    # Capture (original_letter, text) pairs, then shuffle the order.
    # Tracking by original letter (not by text) avoids mis-resolving
    # when two distractors happen to share text.
    pairs = [(L, opts.get(L, "")) for L in _LETTERS]
    random.shuffle(pairs)

    new_options: dict[str, str] = {}
    new_correct: Optional[str] = None
    for new_idx, (old_letter, text) in enumerate(pairs):
        new_letter = _LETTERS[new_idx]
        new_options[new_letter] = text
        if old_letter == correct_old:
            new_correct = new_letter

    question["options"] = new_options
    if new_correct:
        question["correct_letter"] = new_correct


# ── Endpoints — generation ─────────────────────────────────────────────────


@router.post("/quiz", response_model=GenerationDetail, status_code=status.HTTP_201_CREATED)
async def generate_quiz(
    body: QuizGenerateRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> GenerationDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    # Cap check up front — fail fast before paying for retrieval / LLM.
    await _check_cap(pool, user_uuid)

    exam_chunks, corpus_chunks = await _retrieve_for_topic(body.topic)
    if not corpus_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "No regulation passages found for this topic. Try a more "
                "specific topic (e.g. 'lifeboat inspection requirements' "
                "instead of 'lifeboats')."
            ),
        )

    context = _format_chunks_for_prompt(exam_chunks, corpus_chunks)
    user_payload = (
        f"TOPIC: {body.topic}\n\n"
        f"Generate a 10-question quiz on the topic above. Each correct answer "
        f"must cite a specific section from the regulation passages below.\n\n"
        f"{context}"
    )

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    try:
        response = await anthropic_client.messages.create(
            model=_QUIZ_MODEL,
            max_tokens=_QUIZ_MAX_TOKENS,
            system=_QUIZ_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
    except Exception as exc:
        logger.warning("quiz generation failed: %s: %s", type(exc).__name__, str(exc)[:200])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Quiz generation temporarily unavailable. Try again in a moment.",
        )

    parsed = _parse_json_response(text)
    if not parsed or "questions" not in parsed:
        logger.warning("quiz JSON parse failed: %s", text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Quiz generator returned an unparseable response. Please try again.",
        )

    # Bias fix — shuffle each question's options so the correct answer
    # isn't clustered in B/C (Haiku positional bias). Done BEFORE citation
    # verification so all subsequent metadata reads from the post-shuffle
    # question shape.
    questions = parsed.get("questions") or []
    for q in questions:
        _shuffle_question_options(q)

    # Citation verification — every question's citation must resolve to
    # a real entry in the regulations corpus. We don't reject the
    # generation on a partial miss; we annotate per-question and surface
    # an aggregate confidence to the frontend.
    quiz_citations = [(q.get("citation") or "").strip() for q in questions]
    verification = await _verify_citations(pool, quiz_citations)
    for q in questions:
        cite = (q.get("citation") or "").strip()
        q["verified"] = bool(verification.get(cite, False))
    verified_count = sum(1 for q in questions if q.get("verified"))
    parsed["citation_verification_rate"] = (
        round(verified_count / len(questions), 4) if questions else 0.0
    )
    parsed["citations_verified"] = verified_count
    parsed["citations_total"] = len(questions)

    title = (parsed.get("title") or f"Quiz: {body.topic}")[:200]
    topic_key = (parsed.get("topic_key") or "").strip() or None

    row = await pool.fetchrow(
        """
        INSERT INTO study_generations
          (user_id, kind, topic, topic_key, title, content_json,
           model_used, input_tokens, output_tokens)
        VALUES ($1, 'quiz', $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, created_at, archived_at
        """,
        user_uuid, body.topic, topic_key, title,
        json.dumps(parsed),
        _QUIZ_MODEL, in_tok, out_tok,
    )

    return GenerationDetail(
        id=str(row["id"]),
        kind="quiz",
        title=title,
        topic=body.topic,
        topic_key=topic_key,
        content_json=parsed,
        model_used=_QUIZ_MODEL,
        created_at=row["created_at"].isoformat(),
        archived_at=None,
    )


@router.post("/guide", response_model=GenerationDetail, status_code=status.HTTP_201_CREATED)
async def generate_guide(
    body: GuideGenerateRequest,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> GenerationDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    await _check_cap(pool, user_uuid)

    exam_chunks, corpus_chunks = await _retrieve_for_topic(body.topic, k_exam_bank=2, k_corpus=8)
    if not corpus_chunks:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No regulation passages found for this topic. Try a more specific phrasing.",
        )

    context = _format_chunks_for_prompt(exam_chunks, corpus_chunks)
    depth_label = "deep dive (~1500-2500 words)" if body.deep_dive else "fast guide (~600-1200 words)"
    user_payload = (
        f"TOPIC: {body.topic}\n"
        f"LENGTH: {depth_label}\n\n"
        f"Generate a {depth_label} on the topic above. Each section must "
        f"cite at least one specific section from the regulation passages below.\n\n"
        f"{context}"
    )

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    model = _GUIDE_MODEL_DEEP if body.deep_dive else _GUIDE_MODEL_FAST
    max_tokens = _GUIDE_MAX_TOKENS_DEEP if body.deep_dive else _GUIDE_MAX_TOKENS_FAST

    try:
        response = await anthropic_client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=_GUIDE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = "".join(getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text")
        in_tok = response.usage.input_tokens
        out_tok = response.usage.output_tokens
    except Exception as exc:
        logger.warning("guide generation failed: %s: %s", type(exc).__name__, str(exc)[:200])
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Study guide generation temporarily unavailable. Try again in a moment.",
        )

    parsed = _parse_json_response(text)
    if not parsed or "sections" not in parsed:
        logger.warning("guide JSON parse failed: %s", text[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Study guide generator returned an unparseable response. Please try again.",
        )

    # Citation verification — collect every citation from all sections
    # and key_citations, batch-verify, then annotate. We compute the
    # rate at the unique-citation level so a section with 5 citations
    # doesn't dominate the aggregate.
    sections = parsed.get("sections") or []
    all_cites: list[str] = []
    for sec in sections:
        for raw in (sec.get("citations") or []):
            stripped = (raw or "").strip()
            if stripped:
                all_cites.append(stripped)
    for raw in (parsed.get("key_citations") or []):
        stripped = (raw or "").strip()
        if stripped:
            all_cites.append(stripped)
    unique_cites = list(dict.fromkeys(all_cites))   # preserve order, dedupe
    verification = await _verify_citations(pool, unique_cites)
    # Annotate each section with verified_citations / unverified_citations
    for sec in sections:
        sec_cites = [(c or "").strip() for c in (sec.get("citations") or []) if c]
        sec["verified_citations"] = [c for c in sec_cites if verification.get(c, False)]
        sec["unverified_citations"] = [c for c in sec_cites if not verification.get(c, False)]
    parsed["verified_key_citations"] = [
        c for c in (parsed.get("key_citations") or []) if verification.get((c or "").strip(), False)
    ]
    parsed["unverified_key_citations"] = [
        c for c in (parsed.get("key_citations") or []) if not verification.get((c or "").strip(), False)
    ]
    verified_unique = sum(1 for c in unique_cites if verification.get(c, False))
    parsed["citation_verification_rate"] = (
        round(verified_unique / len(unique_cites), 4) if unique_cites else 0.0
    )
    parsed["citations_verified"] = verified_unique
    parsed["citations_total"] = len(unique_cites)

    title = (parsed.get("title") or f"Study Guide: {body.topic}")[:200]
    topic_key = (parsed.get("topic_key") or "").strip() or None

    row = await pool.fetchrow(
        """
        INSERT INTO study_generations
          (user_id, kind, topic, topic_key, title, content_json,
           model_used, input_tokens, output_tokens)
        VALUES ($1, 'guide', $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, created_at, archived_at
        """,
        user_uuid, body.topic, topic_key, title,
        json.dumps(parsed),
        model, in_tok, out_tok,
    )

    return GenerationDetail(
        id=str(row["id"]),
        kind="guide",
        title=title,
        topic=body.topic,
        topic_key=topic_key,
        content_json=parsed,
        model_used=model,
        created_at=row["created_at"].isoformat(),
        archived_at=None,
    )


# ── Endpoints — library ────────────────────────────────────────────────────


@router.get("/library", response_model=list[GenerationSummary])
async def list_library(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    include_archived: bool = False,
    kind: Optional[str] = None,         # filter by 'quiz' or 'guide'
) -> list[GenerationSummary]:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    archive_clause = "" if include_archived else " AND archived_at IS NULL"
    kind_clause = " AND kind = $2" if kind in ("quiz", "guide") else ""
    args: list = [user_uuid]
    if kind in ("quiz", "guide"):
        args.append(kind)

    sql = f"""
        SELECT id, kind, title, topic, topic_key, model_used, created_at, archived_at
        FROM study_generations
        WHERE user_id = $1{archive_clause}{kind_clause}
        ORDER BY created_at DESC
        LIMIT 100
    """
    rows = await pool.fetch(sql, *args)

    return [
        GenerationSummary(
            id=str(r["id"]),
            kind=r["kind"],
            title=r["title"],
            topic=r["topic"],
            topic_key=r["topic_key"],
            model_used=r["model_used"],
            created_at=r["created_at"].isoformat(),
            archived_at=r["archived_at"].isoformat() if r["archived_at"] else None,
        )
        for r in rows
    ]


@router.get("/library/{generation_id}", response_model=GenerationDetail)
async def get_generation(
    generation_id: Annotated[_uuid.UUID, Path()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> GenerationDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    row = await pool.fetchrow(
        """
        SELECT id, kind, title, topic, topic_key, content_json,
               model_used, created_at, archived_at
        FROM study_generations
        WHERE id = $1 AND user_id = $2
        """,
        generation_id, user_uuid,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")
    content = row["content_json"]
    if isinstance(content, str):
        content = json.loads(content)
    return GenerationDetail(
        id=str(row["id"]),
        kind=row["kind"],
        title=row["title"],
        topic=row["topic"],
        topic_key=row["topic_key"],
        content_json=content,
        model_used=row["model_used"],
        created_at=row["created_at"].isoformat(),
        archived_at=row["archived_at"].isoformat() if row["archived_at"] else None,
    )


@router.post("/library/{generation_id}/archive", status_code=status.HTTP_204_NO_CONTENT)
async def archive_generation(
    generation_id: Annotated[_uuid.UUID, Path()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    result = await pool.execute(
        "UPDATE study_generations SET archived_at = NOW() "
        "WHERE id = $1 AND user_id = $2 AND archived_at IS NULL",
        generation_id, user_uuid,
    )
    # asyncpg returns "UPDATE n" — check that we touched a row OR the
    # row exists already-archived (idempotent).
    if result == "UPDATE 0":
        exists = await pool.fetchval(
            "SELECT 1 FROM study_generations WHERE id = $1 AND user_id = $2",
            generation_id, user_uuid,
        )
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")


@router.post("/library/{generation_id}/unarchive", status_code=status.HTTP_204_NO_CONTENT)
async def unarchive_generation(
    generation_id: Annotated[_uuid.UUID, Path()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    result = await pool.execute(
        "UPDATE study_generations SET archived_at = NULL "
        "WHERE id = $1 AND user_id = $2",
        generation_id, user_uuid,
    )
    if result == "UPDATE 0":
        exists = await pool.fetchval(
            "SELECT 1 FROM study_generations WHERE id = $1 AND user_id = $2",
            generation_id, user_uuid,
        )
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Generation not found")


# ── Endpoints — quiz sessions (take-the-quiz) ──────────────────────────────


@router.post("/quiz-sessions", response_model=QuizSessionDetail, status_code=status.HTTP_201_CREATED)
async def start_quiz_session(
    body: QuizSessionStartRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> QuizSessionDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    try:
        gen_uuid = _uuid.UUID(body.generation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid generation_id")

    # Verify ownership + that it's a quiz (not a guide).
    gen = await pool.fetchrow(
        "SELECT kind FROM study_generations WHERE id = $1 AND user_id = $2",
        gen_uuid, user_uuid,
    )
    if not gen:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Quiz not found")
    if gen["kind"] != "quiz":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Generation is not a quiz")

    row = await pool.fetchrow(
        """
        INSERT INTO study_quiz_sessions (user_id, generation_id)
        VALUES ($1, $2)
        RETURNING id, started_at
        """,
        user_uuid, gen_uuid,
    )
    return QuizSessionDetail(
        id=str(row["id"]),
        generation_id=str(gen_uuid),
        answers=[],
        score_pct=None,
        started_at=row["started_at"].isoformat(),
        finished_at=None,
        elapsed_seconds=None,
    )


@router.post("/quiz-sessions/{session_id}/answer", response_model=QuizSessionDetail)
async def submit_answer(
    session_id: Annotated[_uuid.UUID, Path()],
    body: QuizSessionAnswerRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> QuizSessionDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    # Load session + parent generation in one query — we need the
    # correct_letter from the quiz JSON to grade this answer.
    row = await pool.fetchrow(
        """
        SELECT s.id, s.generation_id, s.answers, s.started_at, s.finished_at,
               s.score_pct, s.elapsed_seconds, g.content_json
        FROM study_quiz_sessions s
        JOIN study_generations g ON g.id = s.generation_id
        WHERE s.id = $1 AND s.user_id = $2
        """,
        session_id, user_uuid,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row["finished_at"] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already finished")

    quiz_content = row["content_json"]
    if isinstance(quiz_content, str):
        quiz_content = json.loads(quiz_content)
    questions = quiz_content.get("questions") or []
    if body.q_index >= len(questions):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="q_index out of range")

    correct_letter = questions[body.q_index].get("correct_letter")
    is_correct = body.selected_letter == correct_letter

    new_answer = {
        "q": body.q_index,
        "selected": body.selected_letter,
        "correct_letter": correct_letter,
        "is_correct": is_correct,
        "answered_at": datetime.now(timezone.utc).isoformat(),
    }

    existing = row["answers"]
    if isinstance(existing, str):
        existing = json.loads(existing)
    # Replace if user re-answered the same question (last write wins);
    # otherwise append.
    answers_list: list[dict] = [a for a in (existing or []) if a.get("q") != body.q_index]
    answers_list.append(new_answer)
    answers_list.sort(key=lambda a: a.get("q", 0))

    await pool.execute(
        "UPDATE study_quiz_sessions SET answers = $1 WHERE id = $2",
        json.dumps(answers_list), session_id,
    )

    return QuizSessionDetail(
        id=str(row["id"]),
        generation_id=str(row["generation_id"]),
        answers=[QuizSessionAnswer(**a) for a in answers_list],
        score_pct=float(row["score_pct"]) if row["score_pct"] is not None else None,
        started_at=row["started_at"].isoformat(),
        finished_at=None,
        elapsed_seconds=row["elapsed_seconds"],
    )


@router.post("/quiz-sessions/{session_id}/finish", response_model=QuizSessionDetail)
async def finish_quiz_session(
    session_id: Annotated[_uuid.UUID, Path()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> QuizSessionDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    row = await pool.fetchrow(
        """
        SELECT s.id, s.generation_id, s.answers, s.started_at, s.finished_at,
               g.content_json
        FROM study_quiz_sessions s
        JOIN study_generations g ON g.id = s.generation_id
        WHERE s.id = $1 AND s.user_id = $2
        """,
        session_id, user_uuid,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if row["finished_at"] is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Session already finished")

    answers = row["answers"]
    if isinstance(answers, str):
        answers = json.loads(answers)
    answers = answers or []

    quiz_content = row["content_json"]
    if isinstance(quiz_content, str):
        quiz_content = json.loads(quiz_content)
    total_questions = len(quiz_content.get("questions") or [])
    if total_questions == 0:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Quiz has no questions")

    correct_count = sum(1 for a in answers if a.get("is_correct"))
    score_pct = round((correct_count / total_questions) * 100, 2)

    started_at = row["started_at"]
    finished_at = datetime.now(timezone.utc)
    elapsed = max(0, int((finished_at - started_at).total_seconds()))

    await pool.execute(
        """
        UPDATE study_quiz_sessions
        SET finished_at = $1, score_pct = $2, elapsed_seconds = $3
        WHERE id = $4
        """,
        finished_at, score_pct, elapsed, session_id,
    )

    return QuizSessionDetail(
        id=str(row["id"]),
        generation_id=str(row["generation_id"]),
        answers=[QuizSessionAnswer(**a) for a in answers],
        score_pct=score_pct,
        started_at=started_at.isoformat(),
        finished_at=finished_at.isoformat(),
        elapsed_seconds=elapsed,
    )


@router.get("/quiz-sessions/active", response_model=QuizSessionDetail)
async def get_active_quiz_session(
    generation_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> QuizSessionDetail:
    """Return the most recent UNFINISHED session for this generation.

    Used by the take-quiz page on load to resume across page refreshes
    instead of orphaning the prior session by always creating a new one.
    Returns 404 when there's no resumable session — the frontend treats
    that as a signal to POST /quiz-sessions and create a fresh one.

    NOTE: This route is registered BEFORE `/quiz-sessions/{session_id}`
    on purpose — FastAPI matches in declaration order, and a path
    parameter would otherwise swallow the literal "active" segment.
    """
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    try:
        gen_uuid = _uuid.UUID(generation_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid generation_id")

    row = await pool.fetchrow(
        """
        SELECT id, generation_id, answers, score_pct, started_at,
               finished_at, elapsed_seconds
        FROM study_quiz_sessions
        WHERE user_id = $1 AND generation_id = $2 AND finished_at IS NULL
        ORDER BY started_at DESC
        LIMIT 1
        """,
        user_uuid, gen_uuid,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active session")

    answers = row["answers"]
    if isinstance(answers, str):
        answers = json.loads(answers)

    return QuizSessionDetail(
        id=str(row["id"]),
        generation_id=str(row["generation_id"]),
        answers=[QuizSessionAnswer(**a) for a in (answers or [])],
        score_pct=float(row["score_pct"]) if row["score_pct"] is not None else None,
        started_at=row["started_at"].isoformat(),
        finished_at=None,
        elapsed_seconds=row["elapsed_seconds"],
    )


@router.get("/quiz-sessions/{session_id}", response_model=QuizSessionDetail)
async def get_quiz_session(
    session_id: Annotated[_uuid.UUID, Path()],
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> QuizSessionDetail:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    row = await pool.fetchrow(
        """
        SELECT id, generation_id, answers, score_pct, started_at,
               finished_at, elapsed_seconds
        FROM study_quiz_sessions
        WHERE id = $1 AND user_id = $2
        """,
        session_id, user_uuid,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    answers = row["answers"]
    if isinstance(answers, str):
        answers = json.loads(answers)

    return QuizSessionDetail(
        id=str(row["id"]),
        generation_id=str(row["generation_id"]),
        answers=[QuizSessionAnswer(**a) for a in (answers or [])],
        score_pct=float(row["score_pct"]) if row["score_pct"] is not None else None,
        started_at=row["started_at"].isoformat(),
        finished_at=row["finished_at"].isoformat() if row["finished_at"] else None,
        elapsed_seconds=row["elapsed_seconds"],
    )


# ── Usage check ────────────────────────────────────────────────────────────


@router.get("/usage", response_model=UsageDTO)
async def get_usage(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> UsageDTO:
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    tier, is_priv = await _fetch_user_tier(pool, user_uuid)

    # Privileged + Captain are both effectively unlimited.
    if is_priv or tier == "captain":
        used = int(await pool.fetchval(
            """
            SELECT COUNT(*) FROM study_generations
            WHERE user_id = $1 AND created_at >= date_trunc('month', NOW())
            """,
            user_uuid,
        ) or 0)
        return UsageDTO(
            tier=tier,
            used_this_month=used,
            cap=None,
            can_generate=True,
        )

    if tier == "mate":
        used = int(await pool.fetchval(
            """
            SELECT COUNT(*) FROM study_generations
            WHERE user_id = $1 AND created_at >= date_trunc('month', NOW())
            """,
            user_uuid,
        ) or 0)
        cap = _MATE_STUDY_CAP_PER_MONTH
        return UsageDTO(
            tier=tier,
            used_this_month=used,
            cap=cap,
            can_generate=used < cap,
        )

    # Free / no-tier — study tools require Mate or higher.
    return UsageDTO(
        tier=tier,
        used_this_month=0,
        cap=0,
        can_generate=False,
    )

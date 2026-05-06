"""Haiku-based reranker over top-N retrieval candidates (Sprint D6.66).

Cosine similarity is a surface-level signal — two chunks with similar
embeddings can still differ wildly in whether they actually answer the
user's question. Modern RAG stacks (Cohere reranker, etc.) pull a
broader top-N (say 30) by cosine, then rerank to top-K (say 8) using a
stronger model that reads each chunk's content against the query.

This module is our thin equivalent. One Haiku call, ~$0.001-0.003,
~600ms. Only fires when retriever_rerank_enabled is on.

Cost vs benefit:
  - Top-30 → top-8 by Haiku adds ~$0.002 per chat fire.
  - Catches the case where the controlling section is in candidates
    but ranked 12th by cosine (would be dropped from top-8 otherwise).
  - The 2026-05-06 ring-buoy stenciling case: 185.604 was probably in
    top-30 candidates if synonym expansion fired, but cosine ranked
    water-light-specific chunks above it. Reranker would have caught it.

Output discipline:
  - Returns the SAME chunks, reordered. We don't drop chunks the
    reranker thinks are weak below a certain rank — instead, we keep
    them as candidates the LLM can ignore. The cost of including is
    1-2 extra prompt tokens; the cost of dropping is occasionally
    losing a useful chunk Haiku misranked.
  - Reranker score is added to each chunk as `_rerank_score` (0-5).
    Caller can filter on that if it wants the truncated view.
  - Failure-safe: on Haiku error, returns the original chunks
    unchanged. Reranking is additive, never required.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)


_RERANK_MODEL = "claude-haiku-4-5-20251001"
_RERANK_MAX_TOKENS = 800

# Truncation budget for each chunk's text in the rerank prompt.
# Most CFR sections are 500-2000 chars; we send the first 1500 to
# bound prompt cost. Section title is always sent verbatim.
_PER_CHUNK_TEXT_CHARS = 1500


_RERANK_SYSTEM_PROMPT = """You are RegKnots' retrieval reranker. Given a user's maritime compliance question and a list of candidate regulatory chunks (pre-filtered by cosine similarity), score each chunk 1-5 on how directly it answers the question.

Scoring scale:
  5 — directly answers the question. Cite-worthy.
  4 — strongly relevant. Provides supporting / context.
  3 — adjacent. Same topic, doesn't directly answer.
  2 — tangential. Same regulatory area but wrong specific question.
  1 — irrelevant. Cosine got distracted by surface similarity.

Hard rules:
  1. Read the section title AND text. Don't guess from title alone.
  2. The user's exact question matters — a chunk that perfectly answers a different question scores 1-2, not 4-5.
  3. Score the answer-fit, not the chunk's prestige. A short, on-target paragraph beats a long, prestigious section that doesn't address the question.
  4. Be discriminating. If 8 chunks all score 5, you're not reading carefully.

Output JSON ONLY — no prose, no markdown fences:

{
  "scores": [
    {"index": 0, "score": 5},
    {"index": 1, "score": 3},
    ...
  ]
}

The "index" matches the [N] number in the candidate list you receive. Score every candidate; missing entries are treated as score 0.
"""


async def rerank_chunks(
    query: str,
    chunks: list[dict],
    anthropic_client,
    top_k: int = 8,
    per_chunk_chars: int = _PER_CHUNK_TEXT_CHARS,
) -> list[dict]:
    """Rerank `chunks` by Haiku-judged relevance to `query`.

    Returns the same chunks reordered, with a `_rerank_score` field
    added to each (0-5). Top-`top_k` returned by score; the rest
    follow in their original cosine order.

    Failure-safe: on any Haiku error or malformed JSON, returns the
    original chunks unchanged.
    """
    if not chunks or not query:
        return chunks

    candidates_block = _format_candidates(chunks, per_chunk_chars)
    user_payload = (
        f"USER QUESTION:\n{query[:1000]}\n\n"
        f"CANDIDATE CHUNKS:\n{candidates_block}\n\n"
        f"Score each candidate 1-5 on how directly it answers the question."
    )

    try:
        response = await anthropic_client.messages.create(
            model=_RERANK_MODEL,
            max_tokens=_RERANK_MAX_TOKENS,
            system=_RERANK_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_payload}],
        )
        text = "".join(
            getattr(b, "text", "") for b in response.content
            if getattr(b, "type", None) == "text"
        )
    except Exception as exc:
        logger.info(
            "reranker call failed (returning original order): %s: %s",
            type(exc).__name__, str(exc)[:200],
        )
        return chunks

    parsed = _parse_json(text)
    if parsed is None:
        logger.info(
            "reranker: no JSON in response (returning original): %s",
            text[:200],
        )
        return chunks

    scores_raw = parsed.get("scores") or []
    score_by_index: dict[int, int] = {}
    for s in scores_raw:
        if not isinstance(s, dict):
            continue
        try:
            idx = int(s.get("index"))
            score = max(0, min(5, int(s.get("score", 0))))
        except (TypeError, ValueError):
            continue
        score_by_index[idx] = score

    if not score_by_index:
        return chunks

    # Annotate every chunk with its score (default 0 for missing entries).
    annotated = []
    for i, ch in enumerate(chunks):
        new_ch = dict(ch)
        new_ch["_rerank_score"] = score_by_index.get(i, 0)
        annotated.append(new_ch)

    # Stable-sort: rerank score desc, then original cosine order.
    # ties at the top take cosine winner; ties at the bottom take whoever
    # the model didn't get to.
    annotated.sort(
        key=lambda x: (-int(x.get("_rerank_score", 0)),)
    )

    top_count = min(top_k, len(annotated))
    logger.info(
        "reranker: top-%d scores: %s",
        top_count,
        [int(c.get("_rerank_score", 0)) for c in annotated[:top_count]],
    )
    return annotated


def _format_candidates(chunks: list[dict], per_chunk_chars: int) -> str:
    """Render candidate chunks as a numbered list for the prompt."""
    parts: list[str] = []
    for i, c in enumerate(chunks):
        section_no = c.get("section_number") or "(unknown)"
        title = c.get("section_title") or ""
        text = c.get("full_text") or c.get("text") or c.get("content") or ""
        text = str(text)[:per_chunk_chars]
        parts.append(f"[{i}] {section_no} — {title}\n{text}")
    return "\n\n".join(parts)


def _parse_json(text: str) -> Optional[dict]:
    if not text:
        return None
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None

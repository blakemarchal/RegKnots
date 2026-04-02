"""
RAG orchestrator.

Steps:
  1. Route query → model selection (Haiku classifier)
  2. Retrieve top 8 relevant chunks (with soft vessel profile re-ranking)
  3. Build formatted context + citation list
  4. Construct Claude messages (system + history + current turn)
  5. Call Claude with selected model
  6. Verify every citation in the response actually exists in the DB
  7. Strip unverified citations, append disclaimer, log to citation_errors
  8. Return ChatResponse
"""

import logging
import re
from uuid import UUID

import asyncpg
from anthropic import AsyncAnthropic

from rag.context import build_context
from rag.models import ChatMessage, ChatResponse, CitedRegulation
from rag.prompts import NAVIGATION_AID_REMINDER, SYSTEM_PROMPT
from rag.retriever import retrieve
from rag.router import route_query

logger = logging.getLogger(__name__)

_MAX_HISTORY = 10
_MAX_TOKENS = 2048

# Matches both "(46 CFR 199.261)" and bare "46 CFR 199.261" — same as parseMessage.ts
_CFR_RE = re.compile(r"\(?(\d+)\s+CFR\s+([\d]+(?:\.[\d]+(?:-[\d]+)?)?)\)?")

_UNVERIFIED_DISCLAIMER = (
    "\n\n*Note: One or more cited sections could not be verified in the current "
    "regulation database. Please verify directly on eCFR.*"
)


async def verify_citations(
    cited_regulations: list[CitedRegulation],
    pool: asyncpg.Pool,
) -> tuple[list[CitedRegulation], list[str]]:
    """Verify each cited regulation actually exists in the regulations table.

    Args:
        cited_regulations: List of CitedRegulation objects to check.
        pool:              asyncpg connection pool.

    Returns:
        (verified, unverified) where verified is the subset found in the DB
        and unverified is a list of section_number strings not found.
    """
    verified: list[CitedRegulation] = []
    unverified: list[str] = []

    for reg in cited_regulations:
        exists = await pool.fetchval(
            """
            SELECT 1 FROM regulations
            WHERE source = $1 AND section_number = $2
            LIMIT 1
            """,
            reg.source,
            reg.section_number,
        )
        if exists:
            verified.append(reg)
        else:
            logger.warning(
                "Citation not found in DB — source=%r section=%r",
                reg.source,
                reg.section_number,
            )
            unverified.append(reg.section_number)

    return verified, unverified


def _extract_text_citations(answer: str) -> list[CitedRegulation]:
    """Extract CFR citations mentioned in answer text that aren't already in the
    cited_regulations list from context retrieval.

    Returns CitedRegulation stubs (section_title left blank) for DB lookup.
    """
    stubs: list[CitedRegulation] = []
    seen: set[str] = set()

    for m in _CFR_RE.finditer(answer):
        title = m.group(1)
        section = m.group(2)
        section_number = f"{title} CFR {section}"
        source = f"cfr_{title}"

        if section_number not in seen:
            seen.add(section_number)
            stubs.append(
                CitedRegulation(
                    source=source,
                    section_number=section_number,
                    section_title="",
                )
            )

    return stubs


async def _log_citation_errors(
    unverified: list[str],
    conversation_id: UUID,
    answer: str,
    model_used: str,
    pool: asyncpg.Pool,
) -> None:
    """Insert one row per unverified citation into citation_errors."""
    # Truncate message_content to avoid bloating the log table
    content_preview = answer[:1000] if len(answer) > 1000 else answer

    for section_number in unverified:
        await pool.execute(
            """
            INSERT INTO citation_errors
                (conversation_id, message_content, unverified_citation, model_used)
            VALUES ($1, $2, $3, $4)
            """,
            conversation_id,
            content_preview,
            section_number,
            model_used,
        )
    logger.info(
        "Logged %d citation error(s) for conversation %s",
        len(unverified),
        conversation_id,
    )


async def chat(
    query: str,
    conversation_history: list[ChatMessage],
    vessel_profile: dict | None,
    pool: asyncpg.Pool,
    anthropic_client: AsyncAnthropic,
    openai_api_key: str,
    conversation_id: UUID,
) -> ChatResponse:
    """Run the full RAG pipeline and return a ChatResponse.

    Args:
        query:                The user's current question.
        conversation_history: Prior messages for this conversation.
        vessel_profile:       Dict with vessel_type, route_type, cargo_types — or None.
        pool:                 asyncpg connection pool.
        anthropic_client:     Shared AsyncAnthropic client (caller owns lifecycle).
        openai_api_key:       Key for OpenAI query embedding.
        conversation_id:      UUID of the conversation (new or existing).
    """
    # 1. Route
    route = await route_query(query, anthropic_client)
    logger.info(f"Routed query to {route.model} (score={route.score})")

    # 2. Retrieve
    chunks = await retrieve(
        query=query,
        pool=pool,
        openai_api_key=openai_api_key,
        vessel_profile=vessel_profile,
        limit=8,
    )
    logger.info(f"Retrieved {len(chunks)} chunks")

    # 3. Build context
    context_str, cited = build_context(chunks)

    # 4. Construct messages
    history = conversation_history[-_MAX_HISTORY:]
    messages = [{"role": msg.role, "content": msg.content} for msg in history]

    user_content = (
        f"{NAVIGATION_AID_REMINDER}\n\n"
        f"Regulation context:\n{context_str}\n\n"
        f"Question: {query}"
    )
    messages.append({"role": "user", "content": user_content})

    # 5. Call Claude
    response = await anthropic_client.messages.create(
        model=route.model,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    )

    answer = response.content[0].text

    # 6. Verify citations ─────────────────────────────────────────────────────
    #
    # a) Verify the cited_regulations list from context retrieval.
    #    These come from the DB so should always pass, but we verify anyway
    #    as a belt-and-suspenders check.
    verified_cited, unverified_from_context = await verify_citations(cited, pool)

    # b) Extract any additional CFR references Claude added in the answer text
    #    that weren't in the context retrieval list, and verify those too.
    context_section_numbers = {r.section_number for r in cited}
    text_stubs = [
        stub
        for stub in _extract_text_citations(answer)
        if stub.section_number not in context_section_numbers
    ]

    if text_stubs:
        _, unverified_from_text = await verify_citations(text_stubs, pool)
    else:
        unverified_from_text = []

    # Deduplicated combined list of unverified section numbers
    all_unverified = list(
        dict.fromkeys(unverified_from_context + unverified_from_text)
    )

    # 7. Handle unverified citations ──────────────────────────────────────────
    if all_unverified:
        answer = answer + _UNVERIFIED_DISCLAIMER
        await _log_citation_errors(
            unverified=all_unverified,
            conversation_id=conversation_id,
            answer=answer,
            model_used=route.model,
            pool=pool,
        )

    return ChatResponse(
        answer=answer,
        conversation_id=conversation_id,
        cited_regulations=verified_cited,
        model_used=route.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        unverified_citations=all_unverified,
    )

"""
POST /chat — authenticated RAG chat endpoint.

Flow:
  1. Validate auth (Bearer JWT)
  2. Load vessel profile from DB if vessel_id provided
  3. Load last 10 messages from conversation if conversation_id provided
  4. Create new conversation record if none provided
  5. Call engine.chat()
  6. Persist user message + assistant response to messages table
  7. Return ChatResponse
"""

import asyncio
import logging
import uuid
from typing import Annotated

import asyncpg
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Maps full Anthropic model IDs to the short aliases stored in the DB
_MODEL_ALIAS: dict[str, str] = {
    "claude-haiku-4-5-20251001": "haiku",
    "claude-sonnet-4-6": "sonnet",
    "claude-opus-4-6": "opus",
}


@router.post("", status_code=status.HTTP_200_OK)
async def chat_endpoint(
    body: "ChatRequestBody",
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
):
    from rag.engine import chat
    from rag.models import ChatMessage, ChatResponse

    anthropic_client: AsyncAnthropic = request.app.state.anthropic
    openai_api_key: str = request.app.state.openai_api_key

    # 1. Load vessel profile
    vessel_profile: dict | None = None
    if body.vessel_id:
        row = await pool.fetchrow(
            """
            SELECT vessel_type, route_types, cargo_types
            FROM vessels
            WHERE id = $1 AND user_id = $2
            """,
            body.vessel_id,
            uuid.UUID(current_user.user_id),
        )
        if row:
            vessel_profile = {
                "vessel_type": row["vessel_type"],
                "route_types": list(row["route_types"] or []),
                "cargo_types": list(row["cargo_types"] or []),
            }

    # 2. Resolve conversation — load history or create new record
    conversation_id = body.conversation_id
    is_new_conversation = conversation_id is None
    history: list[ChatMessage] = []

    if conversation_id is not None:
        # Verify ownership
        exists = await pool.fetchval(
            "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
            conversation_id,
            uuid.UUID(current_user.user_id),
        )
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        rows = await pool.fetch(
            """
            SELECT role, content FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at DESC
            LIMIT 10
            """,
            conversation_id,
        )
        history = [ChatMessage(role=r["role"], content=r["content"]) for r in reversed(rows)]
    else:
        conversation_id = await pool.fetchval(
            """
            INSERT INTO conversations (user_id, vessel_id)
            VALUES ($1, $2)
            RETURNING id
            """,
            uuid.UUID(current_user.user_id),
            body.vessel_id,
        )

    # 3. Run RAG engine
    response: ChatResponse = await chat(
        query=body.query,
        conversation_history=history,
        vessel_profile=vessel_profile,
        pool=pool,
        anthropic_client=anthropic_client,
        openai_api_key=openai_api_key,
        conversation_id=conversation_id,
    )

    # 4. Resolve cited regulation UUIDs for FK storage
    cited_ids: list[uuid.UUID] = []
    if response.cited_regulations:
        section_numbers = [c.section_number for c in response.cited_regulations]
        id_rows = await pool.fetch(
            """
            SELECT DISTINCT ON (section_number) id
            FROM regulations
            WHERE section_number = ANY($1)
            """,
            section_numbers,
        )
        cited_ids = [r["id"] for r in id_rows]

    # 5. Persist messages
    model_alias = _MODEL_ALIAS.get(response.model_used)
    total_tokens = response.input_tokens + response.output_tokens

    await pool.execute(
        """
        INSERT INTO messages (conversation_id, role, content, cited_regulation_ids)
        VALUES ($1, 'user', $2, '{}')
        """,
        conversation_id,
        body.query,
    )
    await pool.execute(
        """
        INSERT INTO messages
            (conversation_id, role, content, model_used, tokens_used, cited_regulation_ids)
        VALUES ($1, 'assistant', $2, $3, $4, $5)
        """,
        conversation_id,
        response.answer,
        model_alias,
        total_tokens,
        cited_ids,
    )

    # 6. Fire background title generation for brand-new conversations
    if is_new_conversation:
        asyncio.create_task(
            _generate_title(
                conversation_id=conversation_id,
                query=body.query,
                anthropic_client=anthropic_client,
                pool=pool,
            )
        )

    return response


async def _generate_title(
    conversation_id: uuid.UUID,
    query: str,
    anthropic_client: AsyncAnthropic,
    pool: asyncpg.Pool,
) -> None:
    """Generate a 4-6 word title for a new conversation using Haiku. Non-blocking."""
    try:
        msg = await anthropic_client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=24,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Generate a 4-6 word title for a maritime compliance conversation "
                        f"that starts with this question: {query!r}\n"
                        "Respond with only the title, no punctuation, no quotes."
                    ),
                }
            ],
        )
        title = msg.content[0].text.strip()[:120] if msg.content else None
        if title:
            await pool.execute(
                "UPDATE conversations SET title = $1 WHERE id = $2 AND title IS NULL",
                title,
                conversation_id,
            )
    except Exception:
        pass  # Never affect the chat response


# ── Request body defined here to avoid circular import with rag.models ───────

from pydantic import BaseModel  # noqa: E402


class ChatRequestBody(BaseModel):
    query: str
    conversation_id: uuid.UUID | None = None
    vessel_id: uuid.UUID | None = None

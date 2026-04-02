"""
GET /conversations          — list current user's conversations (newest first, limit 50)
GET /conversations/{id}/messages — full message thread with citations resolved
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/conversations", tags=["conversations"])


# ── Response models ────────────────────────────────────────────────────────────

class ConversationSummary(BaseModel):
    id: str
    title: str
    updated_at: str
    vessel_name: str | None


class CitedReg(BaseModel):
    source: str
    section_number: str
    section_title: str | None


class ConversationMessage(BaseModel):
    role: str
    content: str
    cited_regulations: list[CitedReg]
    created_at: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ConversationSummary])
async def list_conversations(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> list[ConversationSummary]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id,
                COALESCE(
                    c.title,
                    LEFT(
                        (SELECT content FROM messages m
                         WHERE m.conversation_id = c.id AND m.role = 'user'
                         ORDER BY m.created_at ASC LIMIT 1),
                        60
                    )
                ) AS title,
                c.updated_at,
                v.name AS vessel_name
            FROM conversations c
            LEFT JOIN vessels v ON v.id = c.vessel_id
            WHERE c.user_id = $1
            ORDER BY c.updated_at DESC
            LIMIT 50
            """,
            uuid.UUID(user.user_id),
        )

    return [
        ConversationSummary(
            id=str(r["id"]),
            title=r["title"] or "Untitled conversation",
            updated_at=r["updated_at"].isoformat(),
            vessel_name=r["vessel_name"],
        )
        for r in rows
    ]


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessage])
async def get_conversation_messages(
    conversation_id: Annotated[uuid.UUID, Path()],
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> list[ConversationMessage]:
    async with pool.acquire() as conn:
        # Verify ownership
        owner = await conn.fetchval(
            "SELECT id FROM conversations WHERE id = $1 AND user_id = $2",
            conversation_id,
            uuid.UUID(user.user_id),
        )
        if not owner:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        rows = await conn.fetch(
            """
            SELECT role, content, cited_regulation_ids, created_at
            FROM messages
            WHERE conversation_id = $1
            ORDER BY created_at ASC
            """,
            conversation_id,
        )

    result: list[ConversationMessage] = []
    for row in rows:
        cited_ids: list[uuid.UUID] = list(row["cited_regulation_ids"] or [])
        cited_regs: list[CitedReg] = []

        if cited_ids:
            async with pool.acquire() as conn:
                reg_rows = await conn.fetch(
                    """
                    SELECT DISTINCT ON (section_number) source, section_number, section_title
                    FROM regulations
                    WHERE id = ANY($1)
                    ORDER BY section_number, created_at
                    """,
                    cited_ids,
                )
            cited_regs = [
                CitedReg(
                    source=r["source"],
                    section_number=r["section_number"],
                    section_title=r["section_title"],
                )
                for r in reg_rows
            ]

        result.append(
            ConversationMessage(
                role=row["role"],
                content=row["content"],
                cited_regulations=cited_regs,
                created_at=row["created_at"].isoformat(),
            )
        )

    return result

"""
GET /conversations                       — list current user's conversations (newest first, limit 50)
GET /conversations/search?q=<term>       — search across the user's message content
GET /conversations/{id}/messages         — full message thread with citations resolved
GET /conversations/{id}/export           — single conversation export (JSON, with citations)
GET /conversations/export-all            — bulk export of last 100 conversations
"""

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
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


class ConversationSearchResult(BaseModel):
    """Search hit: a conversation containing at least one matching message."""
    id: str
    title: str
    updated_at: str
    vessel_name: str | None
    matched_role: str          # 'user' or 'assistant' for the matched message
    matched_preview: str       # ≤280 char excerpt of the matched message
    matched_at: str            # ISO timestamp of the matched message


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
    workspace_id: Annotated[uuid.UUID | None, Query(description="Filter to a workspace context. Omit for personal chat.")] = None,
) -> list[ConversationSummary]:
    """List conversations for the current user.

    Default (no workspace_id query param): returns the user's PERSONAL
    conversations only. Behavior identical to pre-D6.49.

    With ?workspace_id=<id>: returns conversations bound to that
    workspace. Caller must be a member of the workspace, else 403.
    All workspace members see all of the workspace's conversations.
    """
    user_uuid = uuid.UUID(user.user_id)

    if workspace_id is None:
        # PERSONAL CONTEXT — bit-identical to pre-D6.49 query path.
        # Includes only conversations where workspace_id IS NULL so a
        # workspace member's workspace conversations don't bleed into
        # their personal list.
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
                WHERE c.user_id = $1 AND c.workspace_id IS NULL
                ORDER BY c.updated_at DESC
                LIMIT 50
                """,
                user_uuid,
            )
    else:
        # WORKSPACE CONTEXT — caller must be a member.
        async with pool.acquire() as conn:
            role = await conn.fetchval(
                "SELECT role FROM workspace_members "
                "WHERE workspace_id = $1 AND user_id = $2",
                workspace_id, user_uuid,
            )
            if role is None:
                from fastapi import HTTPException, status as _st
                raise HTTPException(
                    status_code=_st.HTTP_403_FORBIDDEN,
                    detail="You are not a member of that workspace.",
                )
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
                WHERE c.workspace_id = $1
                ORDER BY c.updated_at DESC
                LIMIT 50
                """,
                workspace_id,
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


@router.get("/search", response_model=list[ConversationSearchResult])
async def search_conversations(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    q: Annotated[str, Query(min_length=2, max_length=200, description="search term")],
    limit: Annotated[int, Query(ge=1, le=50)] = 25,
    pool=Depends(get_pool),
) -> list[ConversationSearchResult]:
    """Search across the current user's chat history.

    Sprint D6.3c — discreet history search Karynn requested. Matches
    the term against message content (case-insensitive, ILIKE substring).
    Always scoped to user_id — never exposes another user's data.

    For each matching conversation, returns the most recent matching
    message as a preview snippet so the user can see context without
    opening the full thread. Conversations are ordered newest-match
    first so a freshly-asked question surfaces immediately.

    For typical per-user message counts (low thousands at most), ILIKE
    on the existing messages table is fast enough — no full-text index
    or trigram needed yet. Add a tsvector + GIN index if a power user
    accumulates >50K messages and search latency becomes noticeable.
    """
    pattern = f"%{q.strip()}%"
    user_uuid = uuid.UUID(user.user_id)

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT
                c.id,
                COALESCE(
                    c.title,
                    LEFT(
                        (SELECT content FROM messages m_first
                         WHERE m_first.conversation_id = c.id AND m_first.role = 'user'
                         ORDER BY m_first.created_at ASC LIMIT 1),
                        80
                    )
                ) AS title,
                c.updated_at,
                v.name AS vessel_name,
                hit.matched_role,
                hit.matched_preview,
                hit.matched_at
            FROM conversations c
            LEFT JOIN vessels v ON v.id = c.vessel_id
            INNER JOIN LATERAL (
                SELECT
                    m.role AS matched_role,
                    LEFT(m.content, 280) AS matched_preview,
                    m.created_at AS matched_at
                FROM messages m
                WHERE m.conversation_id = c.id
                  AND m.content ILIKE $2
                ORDER BY m.created_at DESC
                LIMIT 1
            ) hit ON TRUE
            WHERE c.user_id = $1
            ORDER BY hit.matched_at DESC
            LIMIT $3
            """,
            user_uuid,
            pattern,
            limit,
        )

    return [
        ConversationSearchResult(
            id=str(r["id"]),
            title=r["title"] or "Untitled conversation",
            updated_at=r["updated_at"].isoformat(),
            vessel_name=r["vessel_name"],
            matched_role=r["matched_role"],
            matched_preview=r["matched_preview"],
            matched_at=r["matched_at"].isoformat(),
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
        # Verify access: personal conversation requires owner match;
        # workspace conversation requires workspace membership.
        # Sprint D6.49.
        conv = await conn.fetchrow(
            "SELECT user_id, workspace_id FROM conversations WHERE id = $1",
            conversation_id,
        )
        if not conv:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")

        user_uuid = uuid.UUID(user.user_id)
        if conv["workspace_id"] is None:
            # Personal — only the owner can read.
            if conv["user_id"] != user_uuid:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        else:
            # Workspace — any member can read.
            role = await conn.fetchval(
                "SELECT role FROM workspace_members "
                "WHERE workspace_id = $1 AND user_id = $2",
                conv["workspace_id"], user_uuid,
            )
            if role is None:
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


# ── Export ─────────────────────────────────────────────────────────────────────

async def _build_export_messages(
    conn,
    conv_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Fetch messages + resolved citations for the given conversation ids."""
    if not conv_ids:
        return {}

    msg_rows = await conn.fetch(
        """
        SELECT conversation_id, role, content, cited_regulation_ids, created_at
        FROM messages
        WHERE conversation_id = ANY($1)
        ORDER BY conversation_id, created_at ASC
        """,
        conv_ids,
    )

    # Collect every regulation id referenced across all messages.
    all_reg_ids: set[uuid.UUID] = set()
    for m in msg_rows:
        for rid in (m["cited_regulation_ids"] or []):
            all_reg_ids.add(rid)

    regs_by_id: dict[uuid.UUID, Any] = {}
    if all_reg_ids:
        reg_rows = await conn.fetch(
            """
            SELECT id, source, section_number, section_title
            FROM regulations
            WHERE id = ANY($1)
            """,
            list(all_reg_ids),
        )
        regs_by_id = {r["id"]: r for r in reg_rows}

    by_conv: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for m in msg_rows:
        cited: list[dict[str, Any]] = []
        seen_sections: set[str] = set()
        for rid in (m["cited_regulation_ids"] or []):
            reg = regs_by_id.get(rid)
            if not reg:
                continue
            if reg["section_number"] in seen_sections:
                continue
            seen_sections.add(reg["section_number"])
            cited.append(
                {
                    "source": reg["source"],
                    "section_number": reg["section_number"],
                    "section_title": reg["section_title"],
                }
            )

        by_conv.setdefault(m["conversation_id"], []).append(
            {
                "role": m["role"],
                "content": m["content"],
                "timestamp": m["created_at"].isoformat(),
                "cited_regulations": cited,
            }
        )

    return by_conv


@router.get("/export-all")
async def export_all_conversations(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Bulk export — last 100 conversations for the current user."""
    async with pool.acquire() as conn:
        conv_rows = await conn.fetch(
            """
            SELECT
                c.id,
                COALESCE(
                    c.title,
                    LEFT(
                        (SELECT content FROM messages m
                         WHERE m.conversation_id = c.id AND m.role = 'user'
                         ORDER BY m.created_at ASC LIMIT 1),
                        80
                    )
                ) AS title,
                c.created_at,
                c.updated_at,
                v.name AS vessel_name
            FROM conversations c
            LEFT JOIN vessels v ON v.id = c.vessel_id
            WHERE c.user_id = $1
            ORDER BY c.updated_at DESC
            LIMIT 100
            """,
            uuid.UUID(user.user_id),
        )

        conv_ids = [c["id"] for c in conv_rows]
        msgs_by_conv = await _build_export_messages(conn, conv_ids)

    conversations = [
        {
            "id": str(c["id"]),
            "title": c["title"] or "Untitled conversation",
            "vessel_name": c["vessel_name"],
            "created_at": c["created_at"].isoformat(),
            "updated_at": c["updated_at"].isoformat(),
            "messages": msgs_by_conv.get(c["id"], []),
        }
        for c in conv_rows
    ]

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_email": user.email,
        "conversation_count": len(conversations),
        "conversations": conversations,
    }


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: Annotated[uuid.UUID, Path()],
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> dict[str, Any]:
    """Export a single conversation belonging to the current user."""
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT
                c.id,
                COALESCE(
                    c.title,
                    LEFT(
                        (SELECT content FROM messages m
                         WHERE m.conversation_id = c.id AND m.role = 'user'
                         ORDER BY m.created_at ASC LIMIT 1),
                        80
                    )
                ) AS title,
                c.created_at,
                c.updated_at,
                v.name AS vessel_name
            FROM conversations c
            LEFT JOIN vessels v ON v.id = c.vessel_id
            WHERE c.id = $1 AND c.user_id = $2
            """,
            conversation_id,
            uuid.UUID(user.user_id),
        )
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        msgs_by_conv = await _build_export_messages(conn, [row["id"]])

    return {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "id": str(row["id"]),
        "title": row["title"] or "Untitled conversation",
        "vessel_name": row["vessel_name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "messages": msgs_by_conv.get(row["id"], []),
    }

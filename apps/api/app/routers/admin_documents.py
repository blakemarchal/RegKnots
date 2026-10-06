"""Admin view of documents users attach in chat (2026-10-05).

The "train on" side of chat uploads (docs/specs/chat-document-upload-2026-10-05.md):
which documents mariners bring, what the internal check made of them, and the
text, to see where answers fall short and which public sources the corpus is
missing. Opening a document's text is audit-logged. Nothing here copies a
user's document anywhere else.
"""
import uuid
from datetime import datetime
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.routers.admin import audit_log, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserDocument(BaseModel):
    id: str
    user_email: str
    filename: str
    title: str
    mime_type: str
    size_bytes: int
    pages: int | None
    chunk_count: int
    status: str
    error: str | None
    doc_type: str | None
    maritime: bool | None
    summary: str | None
    kept: bool
    delete_after: datetime | None
    created_at: datetime
    last_used_at: datetime | None
    questions: int          # user messages it was attached to


class AdminDocumentText(BaseModel):
    id: str
    user_email: str
    title: str
    filename: str
    doc_type: str | None
    summary: str | None
    sections: list[dict]    # [{section, text}] in document order


@router.get("/user-documents", response_model=list[AdminUserDocument])
async def list_user_documents(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    exclude_internal: bool = Query(True),
    limit: int = Query(200, ge=1, le=500),
) -> list[AdminUserDocument]:
    uf = " AND u.is_internal IS NOT TRUE AND u.is_admin IS NOT TRUE" if exclude_internal else ""
    rows = await pool.fetch(
        f"""
        SELECT d.id, u.email AS user_email, d.filename, d.title, d.mime_type, d.size_bytes, d.pages,
               d.chunk_count, d.status, d.error, d.doc_type, d.maritime, d.summary, d.kept,
               d.delete_after, d.created_at, d.last_used_at,
               (SELECT count(*) FROM messages m WHERE d.id = ANY(m.document_ids)) AS questions
        FROM user_documents d JOIN users u ON u.id = d.user_id
        WHERE true{uf}
        ORDER BY d.created_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [AdminUserDocument(**{**dict(r), "id": str(r["id"])}) for r in rows]


@router.get("/user-documents/{document_id}/text", response_model=AdminDocumentText)
async def user_document_text(
    document_id: uuid.UUID,
    admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AdminDocumentText:
    doc = await pool.fetchrow(
        """
        SELECT d.id, u.email AS user_email, d.title, d.filename, d.doc_type, d.summary
        FROM user_documents d JOIN users u ON u.id = d.user_id WHERE d.id = $1
        """,
        document_id,
    )
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    chunks = await pool.fetch(
        "SELECT section, text FROM user_document_chunks WHERE document_id = $1 ORDER BY position", document_id)
    sections: list[dict] = []
    for c in chunks:
        if sections and sections[-1]["section"] == c["section"]:
            sections[-1]["text"] += "\n\n" + c["text"]
        else:
            sections.append({"section": c["section"], "text": c["text"]})
    await audit_log(pool, admin, "view_user_document", str(document_id),
                    {"user_email": doc["user_email"], "title": doc["title"]})
    return AdminDocumentText(id=str(doc["id"]), user_email=doc["user_email"], title=doc["title"],
                             filename=doc["filename"], doc_type=doc["doc_type"], summary=doc["summary"],
                             sections=sections)

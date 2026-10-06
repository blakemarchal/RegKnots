"""Documents a user attaches in chat (2026-10-05).

Upload, list, check on and delete the user's own documents, and resolve a
[Doc: title §section] citation to its text. Processing runs in the Celery
worker (app.tasks.process_user_document); see app/user_docs.py.

Access: only the owner, on every route. The original file is never served.
"""
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel

from app import user_docs
from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.company_docs import UnreadableDocument
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/me/documents", tags=["user-documents"])


class UserDocument(BaseModel):
    id: str
    title: str
    filename: str
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


class DocumentsList(BaseModel):
    documents: list[UserDocument]
    kept_count: int
    keep_limit: int


class DocCitation(BaseModel):
    title: str
    section: str
    text: str


_COLUMNS = ("id, title, filename, mime_type, size_bytes, pages, chunk_count, status, error, "
            "doc_type, maritime, summary, kept, delete_after, created_at")


def _dto(r) -> UserDocument:
    return UserDocument(**{k: (str(r[k]) if k == "id" else r[k]) for k in _COLUMNS.split(", ")})


async def _limits(pool, user_id: uuid.UUID) -> tuple[int, int]:
    """(documents counting toward the limit, the limit). Pending uploads count:
    most become kept."""
    row = await pool.fetchrow(
        """
        SELECT u.subscription_tier, u.is_admin, u.is_internal,
               (SELECT count(*) FROM user_documents d
                WHERE d.user_id = u.id AND (d.kept OR d.status = 'pending')) AS counted
        FROM users u WHERE u.id = $1
        """,
        user_id,
    )
    limit = user_docs.keep_limit(row["subscription_tier"], bool(row["is_admin"] or row["is_internal"]))
    return int(row["counted"]), limit


@router.get("", response_model=DocumentsList)
async def list_documents(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> DocumentsList:
    uid = uuid.UUID(user.user_id)
    rows = await pool.fetch(
        f"SELECT {_COLUMNS} FROM user_documents WHERE user_id = $1 ORDER BY created_at DESC", uid)
    _, limit = await _limits(pool, uid)
    return DocumentsList(documents=[_dto(r) for r in rows],
                         kept_count=sum(1 for r in rows if r["kept"]), keep_limit=limit)


@router.post("", response_model=UserDocument, status_code=status.HTTP_201_CREATED)
async def upload_document(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    file: UploadFile = File(...),
) -> UserDocument:
    uid = uuid.UUID(user.user_id)
    today = await pool.fetchval(
        "SELECT count(*) FROM user_documents WHERE user_id = $1 AND created_at > now() - interval '1 day'", uid)
    if today >= user_docs.UPLOADS_PER_DAY:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            f"You can upload {user_docs.UPLOADS_PER_DAY} documents a day. Try again tomorrow.")
    counted, limit = await _limits(pool, uid)
    if counted >= limit:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have {counted} saved documents, the most your plan keeps. Delete one in "
            "Account → My documents to add another." + (" Paid plans keep 20." if limit < user_docs.KEEP_LIMIT_PAID else ""),
        )
    content = await file.read(user_docs.MAX_FILE_BYTES + 1)
    if len(content) > user_docs.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Files are limited to 25 MB.")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is empty.")
    try:
        mime = user_docs.sniff_type(content)
    except UnreadableDocument as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    if mime is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Attach a PDF or a Word (.docx) file. For photos, use JPEG, PNG or WebP.")

    doc_id = uuid.uuid4()
    directory = Path(settings.upload_dir) / "user_docs" / str(uid)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc_id}{user_docs.EXTENSIONS[mime]}"
    path.write_bytes(content)
    os.chmod(path, 0o600)

    filename = (file.filename or "document")[:200]
    row = await pool.fetchrow(
        f"""
        INSERT INTO user_documents (id, user_id, filename, title, mime_type, file_path, size_bytes)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING {_COLUMNS}
        """,
        doc_id, uid, filename, user_docs.doc_title(filename), mime, str(path), len(content),
    )
    from app.tasks import process_user_document
    process_user_document.delay(str(doc_id))
    logger.info("user doc %s uploaded by %s (%s, %d bytes)", doc_id, user.email, mime, len(content))
    return _dto(row)


@router.get("/citation", response_model=DocCitation)
async def open_citation(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ref: str = Query(..., max_length=400),
) -> DocCitation:
    """The text behind a [Doc: title §section] citation, from the caller's own documents."""
    hit = await user_docs.lookup(pool, uuid.UUID(user.user_id), ref)
    if hit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That document section wasn't found.")
    return DocCitation(**hit)


@router.get("/{document_id}", response_model=UserDocument)
async def get_document(
    document_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> UserDocument:
    row = await pool.fetchrow(
        f"SELECT {_COLUMNS} FROM user_documents WHERE id = $1 AND user_id = $2",
        document_id, uuid.UUID(user.user_id))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    return _dto(row)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    document_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> None:
    if not await user_docs.delete_document(pool, uuid.UUID(user.user_id), document_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    logger.info("user doc %s deleted by %s", document_id, user.email)

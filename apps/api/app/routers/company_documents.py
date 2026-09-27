"""Company documents in fleet chat (2026-09-27).

Upload, list and delete a workspace's own manuals, and resolve a
[Company: title §section] citation to its text. Processing runs in the Celery
worker (app.tasks.process_company_document); see app/company_docs.py.

Access: any member may list documents and open a citation; owners and admins
upload and delete. Uploads need a trialing or active workspace.
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

from app import company_docs
from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool
from app.routers.workspaces import _require_workspace_role

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["company-documents"])

_MEMBERS = ("owner", "admin", "member")
_MANAGERS = ("owner", "admin")
_EXT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


class CompanyDocument(BaseModel):
    id: str
    title: str
    filename: str
    mime_type: str
    size_bytes: int
    pages: int | None
    chunk_count: int
    status: str
    error: str | None
    created_at: datetime


class CompanyCitation(BaseModel):
    title: str
    section: str
    text: str


def _dto(r) -> CompanyDocument:
    return CompanyDocument(
        id=str(r["id"]), title=r["title"], filename=r["filename"], mime_type=r["mime_type"],
        size_bytes=r["size_bytes"], pages=r["pages"], chunk_count=r["chunk_count"],
        status=r["status"], error=r["error"], created_at=r["created_at"],
    )


_COLUMNS = "id, title, filename, mime_type, size_bytes, pages, chunk_count, status, error, created_at"


def _mime_for(upload: UploadFile) -> str | None:
    if upload.content_type in company_docs.ALLOWED_TYPES:
        return upload.content_type
    # Browsers send .md (and sometimes .docx) as application/octet-stream.
    return _EXT_TYPES.get(Path(upload.filename or "").suffix.lower())


@router.get("/{workspace_id}/documents", response_model=list[CompanyDocument])
async def list_documents(
    workspace_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> list[CompanyDocument]:
    await _require_workspace_role(pool, workspace_id, uuid.UUID(user.user_id), _MEMBERS)
    rows = await pool.fetch(
        f"SELECT {_COLUMNS} FROM workspace_documents WHERE workspace_id = $1 ORDER BY created_at DESC",
        workspace_id,
    )
    return [_dto(r) for r in rows]


@router.post("/{workspace_id}/documents", response_model=CompanyDocument, status_code=status.HTTP_201_CREATED)
async def upload_document(
    workspace_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    file: UploadFile = File(...),
) -> CompanyDocument:
    await _require_workspace_role(pool, workspace_id, uuid.UUID(user.user_id), _MANAGERS)
    ws_status = await pool.fetchval("SELECT status FROM workspaces WHERE id = $1", workspace_id)
    if ws_status not in ("trialing", "active"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Company documents need an active fleet plan.")
    count = await pool.fetchval("SELECT count(*) FROM workspace_documents WHERE workspace_id = $1", workspace_id)
    if count >= company_docs.MAX_DOCS_PER_WORKSPACE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"A fleet can hold {company_docs.MAX_DOCS_PER_WORKSPACE} documents; delete one first.")
    mime = _mime_for(file)
    if mime is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Upload a PDF, Word (.docx), .txt or .md file.")
    content = await file.read()
    if len(content) > company_docs.MAX_FILE_BYTES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Files are limited to 25 MB.")
    if not content:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The file is empty.")

    doc_id = uuid.uuid4()
    directory = Path(settings.upload_dir) / "workspace_docs" / str(workspace_id)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc_id}{company_docs.ALLOWED_TYPES[mime]}"
    path.write_bytes(content)
    os.chmod(path, 0o600)

    filename = (file.filename or "document")[:200]
    row = await pool.fetchrow(
        f"""
        INSERT INTO workspace_documents (id, workspace_id, uploaded_by, filename, title, mime_type, file_path, size_bytes)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING {_COLUMNS}
        """,
        doc_id, workspace_id, uuid.UUID(user.user_id), filename,
        company_docs.title_from_filename(filename), mime, str(path), len(content),
    )
    from app.tasks import process_company_document
    process_company_document.delay(str(doc_id))
    logger.info("company doc %s uploaded to workspace %s by %s (%d bytes)", doc_id, workspace_id, user.email, len(content))
    return _dto(row)


@router.delete("/{workspace_id}/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> None:
    await _require_workspace_role(pool, workspace_id, uuid.UUID(user.user_id), _MANAGERS)
    path = await pool.fetchval(
        "DELETE FROM workspace_documents WHERE id = $1 AND workspace_id = $2 RETURNING file_path",
        document_id, workspace_id,
    )
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        logger.warning("company doc %s: could not delete %s", document_id, path)
    logger.info("company doc %s deleted from workspace %s by %s", document_id, workspace_id, user.email)


@router.get("/{workspace_id}/documents/citation", response_model=CompanyCitation)
async def open_citation(
    workspace_id: uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    ref: str = Query(..., max_length=400),
) -> CompanyCitation:
    """The text behind a [Company: title §section] citation in this workspace."""
    await _require_workspace_role(pool, workspace_id, uuid.UUID(user.user_id), _MEMBERS)
    hit = await company_docs.lookup(pool, workspace_id, ref)
    if hit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That section isn't in this fleet's documents.")
    return CompanyCitation(**hit)

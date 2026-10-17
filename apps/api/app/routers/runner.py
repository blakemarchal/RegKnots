"""The job queue for a laptop runner (2026-10-16): open problem reports
(support_tickets, kind='problem') that an agent on Blake's machine can claim,
work on and complete. Bearer token = REGKNOTS_RUNNER_TOKEN; with no token set
the routes answer 404. The runner's design (cadence, what it may do) follows
the Insights thread's pattern once that session is reachable.

    GET  /runner/jobs?status=open            the queue (oldest first)
    POST /runner/jobs/{id}/claim             {"worker": "insights-laptop"}
    POST /runner/jobs/{id}/complete          {"status": "done"|"wont_fix"|"open", "notes": "..."}
    GET  /runner/jobs/{id}/screenshot        the screenshot, if one was attached
"""
from __future__ import annotations

import hmac
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any

import asyncpg
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.db import get_pool

router = APIRouter(prefix="/runner", tags=["runner"])


def require_runner(authorization: Annotated[str | None, Header()] = None) -> str:
    """The shared token, compared in constant time. 404 keeps the routes
    invisible when the feature is off."""
    token = settings.runner_token
    if not token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not given or not hmac.compare_digest(given, token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bad runner token")
    return "runner"


class Job(BaseModel):
    id: str
    created_at: datetime
    status: str
    subject: str
    message: str
    user_email: str
    user_name: str | None
    context: dict[str, Any]
    has_screenshot: bool
    claimed_by: str | None
    claimed_at: datetime | None
    admin_notes: str | None


class ClaimBody(BaseModel):
    worker: str = Field(min_length=1, max_length=80)


class CompleteBody(BaseModel):
    status: str = Field(pattern="^(done|wont_fix|open)$")
    notes: str = Field(default="", max_length=8000)


def _job(r) -> Job:
    ctx = r["context"]
    if isinstance(ctx, str):
        ctx = json.loads(ctx)
    return Job(id=str(r["id"]), created_at=r["created_at"], status=r["status"], subject=r["subject"],
               message=r["message"], user_email=r["user_email"], user_name=r["user_name"], context=ctx or {},
               has_screenshot=bool(r["screenshot_path"]), claimed_by=r["claimed_by"], claimed_at=r["claimed_at"],
               admin_notes=r["admin_notes"])


_COLS = "id, created_at, status, subject, message, user_email, user_name, context, screenshot_path, claimed_by, claimed_at, admin_notes"


@router.get("/jobs", response_model=list[Job])
async def list_jobs(
    _: Annotated[str, Depends(require_runner)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    status_filter: str = Query(default="open", alias="status", pattern="^(open|working|done|wont_fix|all)$"),
    limit: int = Query(default=20, ge=1, le=100),
) -> list[Job]:
    where = "" if status_filter == "all" else "AND status = $2"
    args = [limit] if status_filter == "all" else [limit, status_filter]
    rows = await pool.fetch(
        f"SELECT {_COLS} FROM support_tickets WHERE kind = 'problem' {where} ORDER BY created_at LIMIT $1", *args)
    return [_job(r) for r in rows]


@router.post("/jobs/{job_id}/claim", response_model=Job)
async def claim_job(job_id: uuid.UUID, body: ClaimBody, _: Annotated[str, Depends(require_runner)],
                    pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Job:
    row = await pool.fetchrow(
        f"""UPDATE support_tickets SET status = 'working', claimed_by = $2, claimed_at = now()
            WHERE id = $1 AND kind = 'problem' AND status = 'open' RETURNING {_COLS}""",
        job_id, body.worker)
    if row is None:
        raise HTTPException(status_code=409, detail="Not an open problem report")
    return _job(row)


@router.post("/jobs/{job_id}/complete", response_model=Job)
async def complete_job(job_id: uuid.UUID, body: CompleteBody, _: Annotated[str, Depends(require_runner)],
                       pool: Annotated[asyncpg.Pool, Depends(get_pool)]) -> Job:
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    note = f"[{stamp}] {body.notes.strip()}" if body.notes.strip() else None
    row = await pool.fetchrow(
        f"""UPDATE support_tickets
               SET status = $2,
                   admin_notes = CASE WHEN $3::text IS NULL THEN admin_notes
                                      ELSE concat_ws(E'\\n', admin_notes, $3::text) END,
                   resolved_at = CASE WHEN $2 IN ('done', 'wont_fix') THEN now() ELSE NULL END
             WHERE id = $1 AND kind = 'problem' RETURNING {_COLS}""",
        job_id, body.status, note)
    if row is None:
        raise HTTPException(status_code=404, detail="No such problem report")
    return _job(row)


@router.get("/jobs/{job_id}/screenshot")
async def job_screenshot(job_id: uuid.UUID, _: Annotated[str, Depends(require_runner)],
                         pool: Annotated[asyncpg.Pool, Depends(get_pool)]):
    path = await pool.fetchval("SELECT screenshot_path FROM support_tickets WHERE id = $1 AND kind = 'problem'", job_id)
    if not path:
        raise HTTPException(status_code=404, detail="No screenshot")
    base = (Path(settings.upload_dir) / "support").resolve()
    file = Path(path).resolve()
    if file.parent != base or not file.is_file():
        raise HTTPException(status_code=404, detail="No screenshot")
    return FileResponse(str(file))

"""Report a problem (2026-10-16): a signed-in user describes what went wrong,
optionally with a screenshot; the app adds where they were and what browser.
It lands in support_tickets as kind='problem' with status 'open', shows in
Admin > Support, and is the job queue a laptop runner picks from (routers/runner.py).
"""
from __future__ import annotations

import html
import json
import logging
import os
import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel

from app import ratelimit, uploads
from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/support", tags=["support"])

MAX_SCREENSHOT = 8 * 1024 * 1024
CONTEXT_KEYS = ("conversation_id", "referrer", "user_agent", "viewport", "language", "build", "online")
_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


class ReportOut(BaseModel):
    id: str
    status: str


def screenshot_dir() -> Path:
    return Path(settings.upload_dir) / "support"


def clean_context(raw: str) -> dict:
    """Only the keys the app sends, each a short string."""
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k in CONTEXT_KEYS:
        v = data.get(k)
        if isinstance(v, (str, int, float, bool)) and str(v).strip():
            out[k] = str(v)[:300]
    return out


@router.post("/report", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
async def report_problem(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    message: Annotated[str, Form()],
    page: Annotated[str, Form()] = "",
    context: Annotated[str, Form()] = "{}",
    screenshot: Annotated[UploadFile | None, File()] = None,
) -> ReportOut:
    text = message.strip()
    if len(text) < 10:
        raise HTTPException(status_code=422, detail="Tell us a little more about what happened (at least 10 characters).")
    if len(text) > 4000:
        raise HTTPException(status_code=422, detail="Please keep the report under 4,000 characters.")
    page = page.strip()[:300]
    ctx = clean_context(context[:4096])
    await ratelimit.problem_report(user.user_id)

    shot_bytes = shot_ext = None
    if screenshot is not None and screenshot.filename:
        data = await uploads.read_capped(screenshot, MAX_SCREENSHOT, "The screenshot is too large (8 MB max).")
        mime = uploads.sniff_image_or_pdf(data)
        if mime not in _EXT:
            raise HTTPException(status_code=422, detail="The screenshot must be a JPEG, PNG or WebP image.")
        shot_bytes, shot_ext = data, _EXT[mime]

    ticket_id = uuid.uuid4()
    shot_path = None
    if shot_bytes:
        directory = screenshot_dir()
        directory.mkdir(parents=True, exist_ok=True)
        shot_path = directory / f"{ticket_id}{shot_ext}"
        shot_path.write_bytes(shot_bytes)
        os.chmod(shot_path, 0o600)

    display_name = user.full_name or user.email
    subject = f"Problem on {page}" if page else "Problem report"
    pool = await get_pool()
    await pool.execute(
        """INSERT INTO support_tickets (id, user_id, user_email, user_name, subject, message, kind, context,
                                        screenshot_path)
           VALUES ($1, $2, $3, $4, $5, $6, 'problem', $7::jsonb, $8)""",
        ticket_id, uuid.UUID(user.user_id), user.email, display_name, subject[:200], text,
        json.dumps(ctx), str(shot_path) if shot_path else None,
    )

    # The inbox copy; the dashboard is the record. Non-fatal.
    try:
        from app.email import FROM_EMAIL, send_email
        rows = "".join(f"<p><strong>{html.escape(k)}:</strong> {html.escape(v)}</p>" for k, v in ctx.items())
        send_email({
            "from": FROM_EMAIL,
            "to": ["support@regknots.com"],
            "reply_to": user.email,
            "subject": f"[Problem] {subject[:120]}",
            "html": (
                f"<p><strong>From:</strong> {html.escape(user.email)} ({html.escape(display_name)})</p>"
                f"<p><strong>Page:</strong> {html.escape(page) or '-'}</p>"
                f"{rows}"
                f"<p><strong>Screenshot:</strong> {'attached in the dashboard' if shot_path else 'none'}</p>"
                f"<hr><p>{html.escape(text).replace(chr(10), '<br>')}</p>"
                f"<p><a href='{settings.app_url}/admin/support'>Open in admin</a></p>"
            ),
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("problem report email failed: %s", exc)
    return ReportOut(id=str(ticket_id), status="open")

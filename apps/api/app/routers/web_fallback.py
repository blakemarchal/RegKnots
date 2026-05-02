"""User-facing endpoints for the web search fallback (D6.48 Phase 2).

Currently exposes the thumbs-up/down feedback collector. Admin endpoints
(replay, recent) live in admin.py. Keeping the user-side endpoints in a
separate router so we can adjust auth + rate-limiting independently.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/web-fallback", tags=["web-fallback"])


class FeedbackBody(BaseModel):
    feedback: Literal["helpful", "not_helpful", "inaccurate"]
    note: str | None = None


@router.post("/{fallback_id}/feedback")
async def submit_feedback(
    fallback_id: UUID,
    body: FeedbackBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> dict:
    """Record user feedback on a surfaced web fallback response.

    Authorization: a user can only submit feedback on a fallback row
    they were the original recipient of (user_id match) — prevents
    bored users from poisoning aggregate stats by browsing other
    users' fallbacks. Admins can submit feedback on any row.
    """
    row = await pool.fetchrow(
        "SELECT user_id, surfaced FROM web_fallback_responses WHERE id = $1",
        fallback_id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Fallback response not found",
        )
    if not row["surfaced"]:
        # Should not happen — we only return fallback_id to the UI for
        # surfaced cards. Defensive guard.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot submit feedback on a non-surfaced response",
        )
    is_admin = bool(getattr(current_user, "is_admin", False))
    if (
        not is_admin
        and row["user_id"] is not None
        and row["user_id"] != current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only submit feedback on your own fallback responses",
        )

    await pool.execute(
        "UPDATE web_fallback_responses "
        "SET user_feedback = $1, "
        "    user_feedback_note = $2, "
        "    user_feedback_at = NOW() "
        "WHERE id = $3",
        body.feedback, body.note, fallback_id,
    )
    return {"ok": True}

"""Onboarding wizard completion tracking.

GET  /onboarding/status    — returns flag + vessel_count + credential_count
                              for the OnboardingGate to decide whether to
                              redirect.
POST /onboarding/complete  — record that the user finished or dismissed
                              the welcome wizard at /welcome
POST /onboarding/reset      — clear the flag so user can re-run the wizard

The wizard itself runs entirely in the frontend; these endpoints only
track state.
"""

import uuid as _uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/onboarding", tags=["onboarding"])


class StatusResponse(BaseModel):
    onboarding_completed_at: str | None
    vessel_count: int
    credential_count: int
    needs_onboarding: bool  # convenience: true if gate should redirect


class CompleteRequest(BaseModel):
    skipped: bool = False
    steps_completed: list[str] = []  # subset of ["vessel", "coi", "credential"]


class CompleteResponse(BaseModel):
    onboarding_completed_at: str


@router.get("/status", response_model=StatusResponse)
async def get_onboarding_status(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StatusResponse:
    """Return enough state for the OnboardingGate to decide whether to
    redirect a user into the welcome wizard.

    Logic: needs_onboarding = (no flag set) AND (no vessels) AND (no credentials)
    Existing users with any data are implicitly considered onboarded.
    """
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    row = await pool.fetchrow(
        "SELECT onboarding_completed_at FROM users WHERE id = $1",
        user_id,
    )
    completed_at = row["onboarding_completed_at"] if row else None

    vessel_count = await pool.fetchval(
        "SELECT COUNT(*) FROM vessels WHERE user_id = $1",
        user_id,
    ) or 0

    credential_count = await pool.fetchval(
        "SELECT COUNT(*) FROM user_credentials WHERE user_id = $1",
        user_id,
    ) or 0

    needs_onboarding = (
        completed_at is None
        and vessel_count == 0
        and credential_count == 0
    )

    return StatusResponse(
        onboarding_completed_at=completed_at.isoformat() if completed_at else None,
        vessel_count=vessel_count,
        credential_count=credential_count,
        needs_onboarding=needs_onboarding,
    )


@router.post("/complete", response_model=CompleteResponse)
async def complete_onboarding(
    body: CompleteRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CompleteResponse:
    """Mark the user as having completed (or dismissed) the welcome wizard."""
    pool = await get_pool()
    now = datetime.now(timezone.utc)
    await pool.execute(
        "UPDATE users SET onboarding_completed_at = $1 WHERE id = $2",
        now, _uuid.UUID(user.user_id),
    )
    return CompleteResponse(onboarding_completed_at=now.isoformat())


@router.post("/reset", response_model=dict)
async def reset_onboarding(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    """Clear the onboarding flag so the user can re-run the wizard."""
    pool = await get_pool()
    await pool.execute(
        "UPDATE users SET onboarding_completed_at = NULL WHERE id = $1",
        _uuid.UUID(user.user_id),
    )
    return {"ok": True}

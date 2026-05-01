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


# Sprint D6.31 — persona + jurisdiction_focus collected at Step 0 of the
# welcome wizard. Both are optional; user can skip and remain NULL.

VALID_PERSONAS = {
    "mariner_shipboard",
    "teacher_instructor",
    "shore_side_compliance",
    "legal_consultant",
    "cadet_student",
    "other",
}

VALID_JURISDICTION_FOCUS = {
    "us", "uk", "au", "sg", "hk", "no", "lr", "mh", "bs",
    "international_mixed",
}

# Sprint D6.33 — verbosity tiers driving the response-style block in
# the prompt. NULL or absent = "standard" (current behavior).
VALID_VERBOSITY = {"brief", "standard", "detailed"}


class PersonaRequest(BaseModel):
    persona: str | None = None
    jurisdiction_focus: str | None = None
    verbosity_preference: str | None = None


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


@router.post("/persona", response_model=dict)
async def update_persona(
    body: PersonaRequest,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    """Sprint D6.31 — set/update persona + jurisdiction_focus for this user.

    Used by the welcome wizard's Step 0 and the account-page edit pane.
    Both fields are independently optional; passing None for either keeps
    the existing DB value unchanged.

    Validates against the known enum sets to keep bogus values out — but
    enforced in app code rather than via DB CHECK constraints so adding a
    new persona or jurisdiction is a code-only change.
    """
    pool = await get_pool()
    if body.persona is not None and body.persona not in VALID_PERSONAS:
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"persona must be one of: {', '.join(sorted(VALID_PERSONAS))}",
        )
    if (
        body.jurisdiction_focus is not None
        and body.jurisdiction_focus not in VALID_JURISDICTION_FOCUS
    ):
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "jurisdiction_focus must be one of: "
                + ", ".join(sorted(VALID_JURISDICTION_FOCUS))
            ),
        )
    if (
        body.verbosity_preference is not None
        and body.verbosity_preference not in VALID_VERBOSITY
    ):
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "verbosity_preference must be one of: "
                + ", ".join(sorted(VALID_VERBOSITY))
            ),
        )
    # Use COALESCE so passing None on a field leaves it unchanged.
    await pool.execute(
        """
        UPDATE users
        SET persona = COALESCE($1, persona),
            jurisdiction_focus = COALESCE($2, jurisdiction_focus),
            verbosity_preference = COALESCE($3, verbosity_preference)
        WHERE id = $4
        """,
        body.persona,
        body.jurisdiction_focus,
        body.verbosity_preference,
        _uuid.UUID(user.user_id),
    )
    return {"ok": True}


@router.get("/persona", response_model=dict)
async def get_persona(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> dict:
    """Return current persona + jurisdiction_focus so the account page
    can pre-fill its edit form."""
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT persona, jurisdiction_focus, verbosity_preference FROM users WHERE id = $1",
        _uuid.UUID(user.user_id),
    )
    return {
        "persona": row["persona"] if row else None,
        "jurisdiction_focus": row["jurisdiction_focus"] if row else None,
        "verbosity_preference": row["verbosity_preference"] if row else None,
    }

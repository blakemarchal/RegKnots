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

# Sprint D6.37 — UI theme preference. NULL = "dark" (current default).
VALID_THEME = {"dark", "light", "auto"}

# Sprint D6.83 follow-up — personas that get Study Tools enabled by
# default. Everyone else has it hidden from the nav until they opt in
# from the account page. Source of truth for the "this user is here
# for exam prep" signal.
STUDY_DEFAULT_PERSONAS = {"cadet_student", "teacher_instructor"}


def _resolve_study_enabled(stored: bool | None, persona: str | None) -> bool:
    """Translate a (possibly NULL) DB value + the user's persona into
    the boolean the frontend reads. NULL means "user hasn't customized
    it" — fall back to persona-based default. Once the user explicitly
    toggles, the stored boolean wins regardless of persona."""
    if stored is not None:
        return stored
    return persona in STUDY_DEFAULT_PERSONAS if persona else False


class PersonaRequest(BaseModel):
    persona: str | None = None
    jurisdiction_focus: str | None = None
    verbosity_preference: str | None = None
    theme_preference: str | None = None
    # D6.83 follow-up — explicit toggle for Study Tools nav visibility.
    # Optional; passing None leaves the stored value unchanged.
    study_tools_enabled: bool | None = None


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
    if (
        body.theme_preference is not None
        and body.theme_preference not in VALID_THEME
    ):
        from fastapi import HTTPException, status as http_status
        raise HTTPException(
            status_code=http_status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "theme_preference must be one of: "
                + ", ".join(sorted(VALID_THEME))
            ),
        )
    # Use COALESCE so passing None on a field leaves it unchanged.
    await pool.execute(
        """
        UPDATE users
        SET persona = COALESCE($1, persona),
            jurisdiction_focus = COALESCE($2, jurisdiction_focus),
            verbosity_preference = COALESCE($3, verbosity_preference),
            theme_preference = COALESCE($4, theme_preference),
            study_tools_enabled = COALESCE($5, study_tools_enabled)
        WHERE id = $6
        """,
        body.persona,
        body.jurisdiction_focus,
        body.verbosity_preference,
        body.theme_preference,
        body.study_tools_enabled,
        _uuid.UUID(user.user_id),
    )

    # Seed the Study Tools default the first time a user picks a persona.
    # If study_tools_enabled is still NULL after the COALESCE above
    # (i.e. the user hasn't ever toggled it explicitly) AND a persona
    # was just set, write the persona-based default. We do this AFTER
    # the COALESCE update so an explicit body.study_tools_enabled
    # always wins over the seeded default.
    if body.persona is not None and body.study_tools_enabled is None:
        seed_default = body.persona in STUDY_DEFAULT_PERSONAS
        await pool.execute(
            """
            UPDATE users
            SET study_tools_enabled = $1
            WHERE id = $2 AND study_tools_enabled IS NULL
            """,
            seed_default,
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
        "SELECT persona, jurisdiction_focus, verbosity_preference, theme_preference, "
        "study_tools_enabled "
        "FROM users WHERE id = $1",
        _uuid.UUID(user.user_id),
    )
    persona_val = row["persona"] if row else None
    study_stored = row["study_tools_enabled"] if row else None
    return {
        "persona": persona_val,
        "jurisdiction_focus": row["jurisdiction_focus"] if row else None,
        "verbosity_preference": row["verbosity_preference"] if row else None,
        "theme_preference": row["theme_preference"] if row else None,
        # Resolved boolean for the frontend; never NULL.
        "study_tools_enabled": _resolve_study_enabled(study_stored, persona_val),
    }

"""Admin: Wheelhouse pilots (growth plan step 4, 2026-10-14).

Pilot codes give a longer workspace trial to an owner who signs up from the
code's link (app/pilots.py). Here: create and pause codes, see who came in
from each, list workspaces with their trial end, and set a workspace's trial
length directly (an existing customer, or a pilot that started without the
link). Every write goes to the admin audit log.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app import pilots
from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.routers.admin import audit_log, require_admin, require_write_admin

router = APIRouter(prefix="/admin", tags=["admin"])


class PilotCode(BaseModel):
    code: str
    label: str
    trial_days: int
    active: bool
    notes: str | None
    created_at: datetime
    link: str
    signups: int
    workspaces: int


class PilotCreate(BaseModel):
    code: str = Field(min_length=2, max_length=39)
    label: str = Field(min_length=1, max_length=120)
    trial_days: int = Field(default=90, ge=1, le=365)
    notes: str | None = Field(default=None, max_length=500)


class PilotUpdate(BaseModel):
    active: bool | None = None
    label: str | None = Field(default=None, max_length=120)
    trial_days: int | None = Field(default=None, ge=1, le=365)
    notes: str | None = Field(default=None, max_length=500)


class AdminWorkspace(BaseModel):
    id: str
    name: str
    owner_email: str
    status: str
    internal_only: bool
    created_at: datetime
    trial_ends_at: datetime
    trial_custom: bool
    members: int
    pilot_code: str | None


class TrialUpdate(BaseModel):
    days: int | None = Field(default=None, ge=1, le=365)   # trial length from creation
    code: str | None = None                                # or a pilot code's length


_PILOT_SQL = f"""
    SELECT p.code, p.label, p.trial_days, p.active, p.notes, p.created_at,
           (SELECT count(*) FROM users u WHERE u.signup_attribution->>'src' = '{pilots.SRC_PREFIX}' || p.code) AS signups,
           (SELECT count(*) FROM workspaces w JOIN users u ON u.id = w.owner_user_id
             WHERE u.signup_attribution->>'src' = '{pilots.SRC_PREFIX}' || p.code) AS workspaces
    FROM pilot_codes p
"""


def _pilot(r) -> PilotCode:
    return PilotCode(**{k: r[k] for k in ("code", "label", "trial_days", "active", "notes", "created_at",
                                          "signups", "workspaces")}, link=pilots.signup_link(r["code"]))


@router.get("/pilots", response_model=list[PilotCode])
async def list_pilots(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> list[PilotCode]:
    return [_pilot(r) for r in await pool.fetch(_PILOT_SQL + " ORDER BY p.created_at DESC")]


@router.post("/pilots", response_model=PilotCode, status_code=201)
async def create_pilot(
    body: PilotCreate,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> PilotCode:
    code = pilots.normalize_code(body.code)
    if not pilots.CODE_RE.match(code):
        raise HTTPException(status_code=422, detail="Use 2-39 lowercase letters, digits or hyphens.")
    try:
        await pool.execute(
            "INSERT INTO pilot_codes (code, label, trial_days, notes, created_by) VALUES ($1, $2, $3, $4, $5)",
            code, body.label.strip(), body.trial_days, body.notes, UUID(admin.user_id),
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status_code=409, detail="That code already exists.")
    await audit_log(pool, admin, "create_pilot_code", code, {"label": body.label, "trial_days": body.trial_days})
    return _pilot(await pool.fetchrow(_PILOT_SQL + " WHERE p.code = $1", code))


@router.patch("/pilots/{code}", response_model=PilotCode)
async def update_pilot(
    code: str,
    body: PilotUpdate,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> PilotCode:
    changes = body.model_dump(exclude_none=True)
    if changes:
        sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(changes))
        done = await pool.execute(f"UPDATE pilot_codes SET {sets} WHERE code = $1", code, *changes.values())
        if done.endswith(" 0"):
            raise HTTPException(status_code=404, detail="No such pilot code")
        await audit_log(pool, admin, "update_pilot_code", code, changes)
    row = await pool.fetchrow(_PILOT_SQL + " WHERE p.code = $1", code)
    if row is None:
        raise HTTPException(status_code=404, detail="No such pilot code")
    return _pilot(row)


_WS_SQL = f"""
    SELECT w.id, w.name, u.email AS owner_email, w.status, w.internal_only, w.created_at,
           {pilots.TRIAL_END_SQL} AS trial_ends_at, (w.trial_ends_at IS NOT NULL) AS trial_custom,
           (SELECT count(*) FROM workspace_members m WHERE m.workspace_id = w.id) AS members,
           CASE WHEN u.signup_attribution->>'src' LIKE '{pilots.SRC_PREFIX}%'
                THEN substr(u.signup_attribution->>'src', {len(pilots.SRC_PREFIX) + 1}) END AS pilot_code
    FROM workspaces w JOIN users u ON u.id = w.owner_user_id
"""


def _ws(r) -> AdminWorkspace:
    return AdminWorkspace(**{**dict(r), "id": str(r["id"])})


@router.get("/workspaces", response_model=list[AdminWorkspace])
async def list_workspaces(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> list[AdminWorkspace]:
    return [_ws(r) for r in await pool.fetch(_WS_SQL + " ORDER BY w.created_at DESC LIMIT 200")]


@router.post("/workspaces/{workspace_id}/trial", response_model=AdminWorkspace)
async def set_workspace_trial(
    workspace_id: UUID,
    body: TrialUpdate,
    admin: Annotated[CurrentUser, Depends(require_write_admin)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AdminWorkspace:
    """Set the trial to `days` from the workspace's creation (or a pilot
    code's length). A workspace that is read-only waiting for a card goes
    back to trialing when the new end is still ahead."""
    days = body.days
    if body.code:
        days = await pool.fetchval("SELECT trial_days FROM pilot_codes WHERE code = $1", body.code)
        if not days:
            raise HTTPException(status_code=404, detail="No such pilot code")
    if not days:
        raise HTTPException(status_code=422, detail="Give days or a pilot code.")
    row = await pool.fetchrow(
        """
        UPDATE workspaces SET
          trial_ends_at = created_at + make_interval(days => $2),
          status = CASE WHEN status = 'card_pending' AND stripe_subscription_id IS NULL
                         AND created_at + make_interval(days => $2) > now() THEN 'trialing' ELSE status END,
          card_pending_started_at = CASE WHEN status = 'card_pending' AND stripe_subscription_id IS NULL
                         AND created_at + make_interval(days => $2) > now() THEN NULL
                         ELSE card_pending_started_at END,
          updated_at = now()
        WHERE id = $1 AND status IN ('trialing', 'card_pending')
        RETURNING id
        """,
        workspace_id, days,
    )
    if row is None:
        raise HTTPException(status_code=409, detail="Only a trialing or card-pending workspace has a trial to set.")
    await audit_log(pool, admin, "set_workspace_trial", str(workspace_id), {"days": days, "code": body.code})
    try:
        import json
        await pool.execute(
            "INSERT INTO workspace_billing_events (workspace_id, event_type, actor_user_id, details) "
            "VALUES ($1, 'trial_set_by_admin', $2, $3::jsonb)",
            workspace_id, UUID(admin.user_id), json.dumps({"days": days, "code": body.code}),
        )
    except Exception:
        pass
    return _ws(await pool.fetchrow(_WS_SQL + " WHERE w.id = $1", workspace_id))

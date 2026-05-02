"""Workspaces — Crew tier (Sprint D6.49).

A workspace is the unit of crew-tier billing AND the unit of vessel
context. One workspace = one vessel; the Owner holds the Stripe card,
Admins manage operational settings, Members use the workspace.

Auth model:
  Owner   exactly one per workspace; holds billing card; can transfer
          ownership; can manage all roles.
  Admin   multiple allowed; manage members + dossier; cannot transfer
          ownership or modify billing.
  Member  read+write to dossier and chat; cannot manage members.

Card-pending state machine (next-session scope, schema already in place):
  - Triggered when Owner transfers ownership OR removes card without
    replacement.
  - Workspace becomes read-only for 30 days while new Owner has the
    chance to add a card. Adding a card → status='active'.
  - Expiry → status='archived' with 90-day retention before purge.

Feature flag:
  settings.crew_tier_enabled       master kill switch (default false)
  settings.crew_tier_internal_only  during staged rollout, only
                                    is_internal users may create or
                                    join workspaces (default true)
"""

import logging
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# ── Pydantic models ─────────────────────────────────────────────────────────


class WorkspaceMemberDTO(BaseModel):
    user_id: str
    email: str
    full_name: str | None
    role: Literal["owner", "admin", "member"]
    joined_at: str
    invited_by: str | None


class WorkspaceDTO(BaseModel):
    id: str
    name: str
    owner_user_id: str
    status: Literal["active", "trialing", "card_pending", "archived", "canceled"]
    seat_cap: int
    member_count: int
    my_role: Literal["owner", "admin", "member"]
    created_at: str
    card_pending_started_at: str | None = None


class HandoffNoteDTO(BaseModel):
    """Rolling free-form note left by the outgoing watch for the
    incoming watch. One per workspace; in-place edits only (no history).
    """
    content: str | None
    updated_at: str | None
    updated_by_email: str | None
    updated_by_name: str | None


class WorkspaceDetailDTO(WorkspaceDTO):
    members: list[WorkspaceMemberDTO]
    handoff_note: HandoffNoteDTO


class HandoffNoteUpdate(BaseModel):
    content: str = Field(max_length=8000)


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InviteMemberBody(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    role: Literal["admin", "member"] = "member"


class ChangeRoleBody(BaseModel):
    role: Literal["admin", "member"]


class TransferOwnershipBody(BaseModel):
    new_owner_user_id: str


# ── Internal helpers ────────────────────────────────────────────────────────


def _ensure_feature_enabled() -> None:
    if not settings.crew_tier_enabled:
        # Behave as though the route doesn't exist at all when the master
        # flag is off — keeps the surface invisible to non-internal users
        # browsing OpenAPI / poking at endpoints.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Not Found",
        )


async def _ensure_internal_or_open(
    user: CurrentUser, pool: asyncpg.Pool,
) -> None:
    if not settings.crew_tier_internal_only:
        return
    is_internal = await pool.fetchval(
        "SELECT is_internal FROM users WHERE id = $1",
        UUID(user.user_id),
    )
    if not is_internal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Crew tier is in internal review — not yet available to all users",
        )


async def _get_member_role(
    pool: asyncpg.Pool, workspace_id: UUID, user_id: UUID,
) -> str | None:
    return await pool.fetchval(
        "SELECT role FROM workspace_members "
        "WHERE workspace_id = $1 AND user_id = $2",
        workspace_id, user_id,
    )


async def _require_workspace_role(
    pool: asyncpg.Pool, workspace_id: UUID, user_id: UUID,
    required: tuple[str, ...],
) -> str:
    role = await _get_member_role(pool, workspace_id, user_id)
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if role not in required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of: {', '.join(required)}",
        )
    return role


async def _log_billing_event(
    pool: asyncpg.Pool, workspace_id: UUID, event_type: str,
    actor_user_id: UUID | None, details: dict,
) -> None:
    """Best-effort audit log. Errors don't fail the parent operation."""
    try:
        import json
        await pool.execute(
            "INSERT INTO workspace_billing_events "
            "(workspace_id, event_type, actor_user_id, details) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            workspace_id, event_type, actor_user_id, json.dumps(details),
        )
    except Exception as exc:
        logger.warning("workspace_billing_events log failed: %s", exc)


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("", response_model=WorkspaceDTO, status_code=201)
async def create_workspace(
    body: CreateWorkspaceBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> WorkspaceDTO:
    """Create a new workspace. Caller becomes Owner. Subject to internal-
    only gate during staged rollout."""
    _ensure_feature_enabled()
    await _ensure_internal_or_open(current_user, pool)

    user_uuid = UUID(current_user.user_id)

    async with pool.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "INSERT INTO workspaces (name, owner_user_id, status) "
                "VALUES ($1, $2, 'trialing') "
                "RETURNING id, name, owner_user_id, status, seat_cap, "
                "         created_at, card_pending_started_at",
                body.name.strip(), user_uuid,
            )
            await conn.execute(
                "INSERT INTO workspace_members "
                "(workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                row["id"], user_uuid,
            )
    await _log_billing_event(
        pool, row["id"], "created", user_uuid,
        {"name": body.name},
    )

    return WorkspaceDTO(
        id=str(row["id"]),
        name=row["name"],
        owner_user_id=str(row["owner_user_id"]),
        status=row["status"],
        seat_cap=row["seat_cap"],
        member_count=1,
        my_role="owner",
        created_at=row["created_at"].isoformat(),
        card_pending_started_at=(
            row["card_pending_started_at"].isoformat()
            if row["card_pending_started_at"] else None
        ),
    )


@router.get("", response_model=list[WorkspaceDTO])
async def list_my_workspaces(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> list[WorkspaceDTO]:
    """List workspaces the caller is a member of."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    rows = await pool.fetch(
        """
        SELECT
          w.id, w.name, w.owner_user_id, w.status, w.seat_cap,
          w.created_at, w.card_pending_started_at,
          wm.role AS my_role,
          (SELECT COUNT(*) FROM workspace_members WHERE workspace_id = w.id)
            AS member_count
        FROM workspaces w
        JOIN workspace_members wm ON wm.workspace_id = w.id
        WHERE wm.user_id = $1
        ORDER BY w.created_at DESC
        """,
        user_uuid,
    )
    return [
        WorkspaceDTO(
            id=str(r["id"]), name=r["name"],
            owner_user_id=str(r["owner_user_id"]),
            status=r["status"], seat_cap=r["seat_cap"],
            member_count=int(r["member_count"]),
            my_role=r["my_role"],
            created_at=r["created_at"].isoformat(),
            card_pending_started_at=(
                r["card_pending_started_at"].isoformat()
                if r["card_pending_started_at"] else None
            ),
        )
        for r in rows
    ]


@router.get("/{workspace_id}", response_model=WorkspaceDetailDTO)
async def get_workspace(
    workspace_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> WorkspaceDetailDTO:
    """Get workspace detail including full member list. Must be a member."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    role = await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner", "admin", "member"),
    )
    ws = await pool.fetchrow(
        "SELECT w.id, w.name, w.owner_user_id, w.status, w.seat_cap, w.created_at, "
        "       w.card_pending_started_at, "
        "       w.handoff_note, w.handoff_note_updated_at, "
        "       u.email AS handoff_editor_email, "
        "       u.full_name AS handoff_editor_name "
        "FROM workspaces w "
        "LEFT JOIN users u ON u.id = w.handoff_note_updated_by_user_id "
        "WHERE w.id = $1",
        workspace_id,
    )
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    members = await pool.fetch(
        """
        SELECT wm.user_id, wm.role, wm.joined_at, wm.invited_by_user_id,
               u.email, u.full_name
        FROM workspace_members wm
        JOIN users u ON u.id = wm.user_id
        WHERE wm.workspace_id = $1
        ORDER BY
          CASE wm.role
            WHEN 'owner' THEN 0
            WHEN 'admin' THEN 1
            ELSE 2
          END,
          wm.joined_at
        """,
        workspace_id,
    )
    return WorkspaceDetailDTO(
        id=str(ws["id"]), name=ws["name"],
        owner_user_id=str(ws["owner_user_id"]),
        status=ws["status"], seat_cap=ws["seat_cap"],
        member_count=len(members), my_role=role,
        created_at=ws["created_at"].isoformat(),
        card_pending_started_at=(
            ws["card_pending_started_at"].isoformat()
            if ws["card_pending_started_at"] else None
        ),
        members=[
            WorkspaceMemberDTO(
                user_id=str(m["user_id"]),
                email=m["email"], full_name=m["full_name"],
                role=m["role"],
                joined_at=m["joined_at"].isoformat(),
                invited_by=str(m["invited_by_user_id"])
                          if m["invited_by_user_id"] else None,
            )
            for m in members
        ],
        handoff_note=HandoffNoteDTO(
            content=ws["handoff_note"],
            updated_at=(ws["handoff_note_updated_at"].isoformat()
                        if ws["handoff_note_updated_at"] else None),
            updated_by_email=ws["handoff_editor_email"],
            updated_by_name=ws["handoff_editor_name"],
        ),
    )


# ── Handoff note ────────────────────────────────────────────────────────────


@router.put("/{workspace_id}/handoff-note", response_model=HandoffNoteDTO)
async def update_handoff_note(
    workspace_id: UUID,
    body: HandoffNoteUpdate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> HandoffNoteDTO:
    """Update the workspace's rolling handoff note. Any member can write
    to it (rotation reality: the watch leaving the vessel might be Mate
    or Engineer, not Captain). Last-editor + timestamp tracked so the
    incoming watch knows who wrote what and when.

    Read-only when the workspace is in card_pending / archived /
    canceled state."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner", "admin", "member"),
    )

    ws_status = await pool.fetchval(
        "SELECT status FROM workspaces WHERE id = $1", workspace_id,
    )
    if ws_status in ("card_pending", "archived", "canceled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Workspace is read-only (status: {ws_status}). "
                "Note edits are paused."
            ),
        )

    updated = await pool.fetchrow(
        "UPDATE workspaces SET "
        "  handoff_note = $1, "
        "  handoff_note_updated_at = NOW(), "
        "  handoff_note_updated_by_user_id = $2, "
        "  updated_at = NOW() "
        "WHERE id = $3 "
        "RETURNING handoff_note, handoff_note_updated_at",
        body.content, user_uuid, workspace_id,
    )
    editor = await pool.fetchrow(
        "SELECT email, full_name FROM users WHERE id = $1", user_uuid,
    )
    return HandoffNoteDTO(
        content=updated["handoff_note"],
        updated_at=updated["handoff_note_updated_at"].isoformat()
                   if updated["handoff_note_updated_at"] else None,
        updated_by_email=editor["email"] if editor else None,
        updated_by_name=editor["full_name"] if editor else None,
    )


@router.post("/{workspace_id}/members",
             response_model=WorkspaceMemberDTO, status_code=201)
async def invite_member(
    workspace_id: UUID,
    body: InviteMemberBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> WorkspaceMemberDTO:
    """Invite an existing RegKnots user to the workspace by email.
    Owner or Admin only. The invited user must already have a RegKnots
    account — we do NOT auto-create accounts (per privacy rule against
    creating accounts on behalf of users)."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner", "admin"),
    )

    # Seat cap check.
    ws = await pool.fetchrow(
        "SELECT seat_cap FROM workspaces WHERE id = $1", workspace_id,
    )
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    current_count = await pool.fetchval(
        "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1",
        workspace_id,
    )
    if current_count >= ws["seat_cap"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Seat cap reached ({ws['seat_cap']}). Remove an inactive "
                   "member first or contact support to upgrade.",
        )

    invitee = await pool.fetchrow(
        "SELECT id, email, full_name, is_internal FROM users WHERE email = $1",
        body.email.strip().lower(),
    )
    if invitee is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No RegKnots account exists for that email. The user "
                   "must sign up first.",
        )
    if (
        settings.crew_tier_internal_only
        and not invitee["is_internal"]
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot invite non-internal users while crew tier is "
                   "in internal review.",
        )

    try:
        new_member = await pool.fetchrow(
            "INSERT INTO workspace_members "
            "(workspace_id, user_id, role, invited_by_user_id) "
            "VALUES ($1, $2, $3, $4) "
            "RETURNING joined_at",
            workspace_id, invitee["id"], body.role, user_uuid,
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User is already a member of this workspace.",
        )

    return WorkspaceMemberDTO(
        user_id=str(invitee["id"]),
        email=invitee["email"], full_name=invitee["full_name"],
        role=body.role,
        joined_at=new_member["joined_at"].isoformat(),
        invited_by=str(user_uuid),
    )


@router.delete("/{workspace_id}/members/{member_user_id}", status_code=204)
async def remove_member(
    workspace_id: UUID,
    member_user_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> None:
    """Remove a member from the workspace. Owner can remove anyone except
    themselves (must transfer first). Admin can remove members but not
    other admins or the owner. A member can remove themselves."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    my_role = await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner", "admin", "member"),
    )
    target_role = await _get_member_role(pool, workspace_id, member_user_id)
    if target_role is None:
        raise HTTPException(404, "Member not found in this workspace")

    is_self_removal = (member_user_id == user_uuid)

    if target_role == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner cannot be removed. Transfer ownership first, "
                   "then remove the previous owner if desired.",
        )
    if my_role == "member" and not is_self_removal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Members can only remove themselves.",
        )
    if my_role == "admin" and target_role == "admin" and not is_self_removal:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin cannot remove another admin. Owner must do that.",
        )

    await pool.execute(
        "DELETE FROM workspace_members "
        "WHERE workspace_id = $1 AND user_id = $2",
        workspace_id, member_user_id,
    )


@router.patch("/{workspace_id}/members/{member_user_id}",
              response_model=WorkspaceMemberDTO)
async def change_member_role(
    workspace_id: UUID,
    member_user_id: UUID,
    body: ChangeRoleBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> WorkspaceMemberDTO:
    """Promote a member to admin, or demote an admin to member.
    Owner only. Owner role itself can only be changed via /transfer."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner",),
    )
    target_role = await _get_member_role(pool, workspace_id, member_user_id)
    if target_role is None:
        raise HTTPException(404, "Member not found in this workspace")
    if target_role == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner role can only be changed via /transfer.",
        )

    await pool.execute(
        "UPDATE workspace_members SET role = $1 "
        "WHERE workspace_id = $2 AND user_id = $3",
        body.role, workspace_id, member_user_id,
    )

    member = await pool.fetchrow(
        "SELECT wm.user_id, wm.role, wm.joined_at, wm.invited_by_user_id, "
        "       u.email, u.full_name "
        "FROM workspace_members wm JOIN users u ON u.id = wm.user_id "
        "WHERE wm.workspace_id = $1 AND wm.user_id = $2",
        workspace_id, member_user_id,
    )
    return WorkspaceMemberDTO(
        user_id=str(member["user_id"]),
        email=member["email"], full_name=member["full_name"],
        role=member["role"],
        joined_at=member["joined_at"].isoformat(),
        invited_by=str(member["invited_by_user_id"])
                  if member["invited_by_user_id"] else None,
    )


@router.post("/{workspace_id}/transfer", response_model=WorkspaceDTO)
async def transfer_ownership(
    workspace_id: UUID,
    body: TransferOwnershipBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> WorkspaceDTO:
    """Transfer Owner role to an existing Admin. Old Owner becomes Admin.
    The workspace enters card_pending state — new Owner has 30 days to
    add a card or the workspace is archived."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner",),
    )
    new_owner_uuid = UUID(body.new_owner_user_id)
    new_owner_role = await _get_member_role(
        pool, workspace_id, new_owner_uuid,
    )
    if new_owner_role is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New owner must already be a member of this workspace.",
        )
    if new_owner_role != "admin":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New owner must be an Admin first. Promote them, then "
                   "retry the transfer.",
        )

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE workspace_members SET role = 'admin' "
                "WHERE workspace_id = $1 AND user_id = $2",
                workspace_id, user_uuid,
            )
            await conn.execute(
                "UPDATE workspace_members SET role = 'owner' "
                "WHERE workspace_id = $1 AND user_id = $2",
                workspace_id, new_owner_uuid,
            )
            updated = await conn.fetchrow(
                "UPDATE workspaces SET "
                "  owner_user_id = $1, "
                "  status = 'card_pending', "
                "  card_pending_started_at = NOW(), "
                "  updated_at = NOW() "
                "WHERE id = $2 "
                "RETURNING id, name, owner_user_id, status, seat_cap, "
                "         created_at, card_pending_started_at",
                new_owner_uuid, workspace_id,
            )
    await _log_billing_event(
        pool, workspace_id, "owner_transferred", user_uuid,
        {
            "from_user_id": str(user_uuid),
            "to_user_id": str(new_owner_uuid),
            "status_after": "card_pending",
            "grace_days": 30,
        },
    )

    return WorkspaceDTO(
        id=str(updated["id"]), name=updated["name"],
        owner_user_id=str(updated["owner_user_id"]),
        status=updated["status"], seat_cap=updated["seat_cap"],
        member_count=await pool.fetchval(
            "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1",
            workspace_id,
        ) or 0,
        my_role="admin",  # caller demoted
        created_at=updated["created_at"].isoformat(),
        card_pending_started_at=(
            updated["card_pending_started_at"].isoformat()
            if updated["card_pending_started_at"] else None
        ),
    )

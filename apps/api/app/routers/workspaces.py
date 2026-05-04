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
import secrets
from datetime import datetime, timezone
from typing import Annotated, Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool
from app.email import send_workspace_invite_email
from app.stripe_service import (
    create_workspace_billing_portal_session,
    create_workspace_checkout_session,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


# Sprint D6.49 — temporary test whitelist. While crew_tier_internal_only
# is True, only users with is_internal=true can create or join
# workspaces. This whitelist provides an additional override path so
# Blake can spin up his other personal accounts (proton, live) and
# his wife's account for testing without flipping is_internal on every
# new email. Remove this list once we open the crew tier publicly.
_CREW_TEST_WHITELIST: frozenset[str] = frozenset({
    "blakemarchal@gmail.com",
    "blakemarchal@proton.me",
    "bmarchal@live.com",
    "hillbryanna11@gmail.com",
})


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


class WorkspaceInviteDTO(BaseModel):
    """A pending or historical invite to join a workspace.

    Surfaced in two places:
      - GET /workspaces/{id}/invites — Owner/Admin list of pending
        invites for one workspace (so they see whom they've invited
        and can rescind).
      - GET /me/invites — caller's own pending invites across all
        workspaces (so signed-in users can accept/decline).
    """
    id: str
    workspace_id: str
    workspace_name: str | None = None  # Populated on /me/invites
    email: str
    role: Literal["admin", "member"]
    status: Literal[
        "pending", "accepted", "declined", "rescinded", "expired"
    ]
    invited_by_email: str | None = None
    invited_by_name: str | None = None
    created_at: str
    expires_at: str


class WorkspaceDetailDTO(WorkspaceDTO):
    members: list[WorkspaceMemberDTO]
    pending_invites: list[WorkspaceInviteDTO]
    handoff_note: HandoffNoteDTO


class HandoffNoteUpdate(BaseModel):
    content: str = Field(max_length=8000)


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class InviteMemberBody(BaseModel):
    # Pydantic's EmailStr enforces the basic shape so we don't have to
    # re-validate downstream. Lowercased before insertion.
    email: EmailStr
    role: Literal["admin", "member"] = "member"


class InviteMemberResponse(BaseModel):
    """The /workspaces/{id}/members POST endpoint can return one of two
    things now (sprint D6.53):
      - kind='member' — invitee already had a RegKnots account; we
        added them straight to workspace_members.
      - kind='invite' — invitee did not exist yet; we created a pending
        invite and emailed them a tokenized signup link.

    Frontend dispatches on `kind` for the success toast.
    """
    kind: Literal["member", "invite"]
    member: WorkspaceMemberDTO | None = None
    invite: WorkspaceInviteDTO | None = None


class ChangeRoleBody(BaseModel):
    role: Literal["admin", "member"]


class TransferOwnershipBody(BaseModel):
    new_owner_user_id: str


class CheckoutBody(BaseModel):
    plan: Literal["monthly", "annual"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


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
    # D6.49 — bypass for the explicit test whitelist (Blake's personal
    # accounts + wife). Cheap email check before hitting the DB.
    if user.email.lower() in _CREW_TEST_WHITELIST:
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


async def _seats_used(
    pool: asyncpg.Pool, workspace_id: UUID,
) -> int:
    """Members + still-pending invites. Pending invites count against
    seat_cap so an admin who fires off 8 invites can't have the 9th
    accept silently fail (D6.53). Expired/rescinded/accepted invites
    don't count — only currently-outstanding ones."""
    members = await pool.fetchval(
        "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1",
        workspace_id,
    )
    pending = await pool.fetchval(
        "SELECT COUNT(*) FROM workspace_invites "
        "WHERE workspace_id = $1 AND status = 'pending' "
        "  AND expires_at > now()",
        workspace_id,
    )
    return int(members or 0) + int(pending or 0)


async def _expire_stale_invites(
    pool: asyncpg.Pool, workspace_id: UUID | None = None,
) -> None:
    """Lazy state transition: pending invites past their expires_at
    become status='expired'. Called from any endpoint that reads
    invites so users don't see stale "pending" rows. Cheap UPDATE; no
    cron needed for this slice."""
    if workspace_id is not None:
        await pool.execute(
            "UPDATE workspace_invites SET status = 'expired' "
            "WHERE workspace_id = $1 AND status = 'pending' "
            "  AND expires_at < now()",
            workspace_id,
        )
    else:
        await pool.execute(
            "UPDATE workspace_invites SET status = 'expired' "
            "WHERE status = 'pending' AND expires_at < now()"
        )


def _invite_row_to_dto(
    row: asyncpg.Record, workspace_name: str | None = None,
) -> WorkspaceInviteDTO:
    return WorkspaceInviteDTO(
        id=str(row["id"]),
        workspace_id=str(row["workspace_id"]),
        workspace_name=workspace_name,
        email=row["email"],
        role=row["role"],
        status=row["status"],
        invited_by_email=row.get("inviter_email"),
        invited_by_name=row.get("inviter_name"),
        created_at=row["created_at"].isoformat(),
        expires_at=row["expires_at"].isoformat(),
    )


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
    # D6.53 — pending invites (with stale-pending sweep). Surfacing them
    # in the member list keeps Owner/Admin honest about real headcount;
    # frontend renders them with a "Pending" pill below the members.
    await _expire_stale_invites(pool, workspace_id)
    invites = await pool.fetch(
        """
        SELECT wi.id, wi.workspace_id, wi.email, wi.role, wi.status,
               wi.created_at, wi.expires_at,
               u.email AS inviter_email, u.full_name AS inviter_name
        FROM workspace_invites wi
        LEFT JOIN users u ON u.id = wi.invited_by_user_id
        WHERE wi.workspace_id = $1 AND wi.status = 'pending'
        ORDER BY wi.created_at DESC
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
        pending_invites=[_invite_row_to_dto(inv) for inv in invites],
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
    # D6.54 — read-only enforcement consolidated to one helper.
    await ensure_workspace_writable(pool, workspace_id)

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
             response_model=InviteMemberResponse, status_code=201)
async def invite_member(
    workspace_id: UUID,
    body: InviteMemberBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> InviteMemberResponse:
    """Invite a user to the workspace by email. Owner or Admin only.

    Two paths (D6.53):
      - Invitee already has a RegKnots account → add directly to
        workspace_members and return kind='member'.
      - Invitee has no account → create a row in workspace_invites,
        email a tokenized link, return kind='invite'. Their first
        action (signup-via-link OR direct signup with the same email)
        will auto-claim the invite.

    Pending invites count against seat_cap so an admin who fires off
    8 invites can't have the 9th accept silently fail.
    """
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner", "admin"),
    )
    # D6.54 — no inviting into a read-only workspace; the invitee
    # would land into a portal where they can't actually do anything.
    await ensure_workspace_writable(pool, workspace_id)

    ws = await pool.fetchrow(
        "SELECT name, seat_cap FROM workspaces WHERE id = $1", workspace_id,
    )
    if ws is None:
        raise HTTPException(404, "Workspace not found")

    # Sweep stale invites BEFORE counting seats so freshly-expired rows
    # don't block a legitimate invite.
    await _expire_stale_invites(pool, workspace_id)

    seats_used = await _seats_used(pool, workspace_id)
    if seats_used >= ws["seat_cap"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Seat cap reached ({ws['seat_cap']} — including pending "
                   "invites). Remove an inactive member or rescind a pending "
                   "invite first, or contact support to upgrade.",
        )

    email_norm = body.email.strip().lower()
    invitee = await pool.fetchrow(
        "SELECT id, email, full_name, is_internal FROM users WHERE email = $1",
        email_norm,
    )

    # ── Path A: existing user → straight to workspace_members ───────────
    if invitee is not None:
        invitee_email = (invitee["email"] or "").lower()
        if (
            settings.crew_tier_internal_only
            and not invitee["is_internal"]
            and invitee_email not in _CREW_TEST_WHITELIST
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

        return InviteMemberResponse(
            kind="member",
            member=WorkspaceMemberDTO(
                user_id=str(invitee["id"]),
                email=invitee["email"], full_name=invitee["full_name"],
                role=body.role,
                joined_at=new_member["joined_at"].isoformat(),
                invited_by=str(user_uuid),
            ),
        )

    # ── Path B: no account → create pending invite + email ──────────────
    # Internal-only gate doesn't apply here — the invitee is brand new
    # and lands in our system via an explicit invite link, which is
    # itself the gating mechanism. The check on the existing-user path
    # above prevents accidental adds of unrelated existing users.

    # Reject duplicate pending invite for same (workspace, email).
    existing_pending = await pool.fetchval(
        "SELECT id FROM workspace_invites "
        "WHERE workspace_id = $1 AND lower(email) = $2 AND status = 'pending'",
        workspace_id, email_norm,
    )
    if existing_pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An invite for that email is already pending. Rescind it "
                   "first if you need to change the role.",
        )

    token = secrets.token_urlsafe(32)
    invite_row = await pool.fetchrow(
        """
        INSERT INTO workspace_invites
          (workspace_id, email, role, token, invited_by_user_id)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, workspace_id, email, role, token, status,
                  created_at, expires_at
        """,
        workspace_id, email_norm, body.role, token, user_uuid,
    )

    # Best-effort send. If email fails the invite still exists; admin
    # can resend or rescind from the UI. We log but don't raise.
    inviter_name = (current_user.full_name or current_user.email).strip()
    try:
        await send_workspace_invite_email(
            to_email=email_norm,
            inviter_name=inviter_name,
            workspace_name=ws["name"],
            token=token,
            role=body.role,
        )
    except Exception as exc:
        logger.warning("workspace invite email failed (%s): %s", email_norm, exc)

    return InviteMemberResponse(
        kind="invite",
        invite=_invite_row_to_dto(invite_row, workspace_name=ws["name"]),
    )


@router.delete(
    "/{workspace_id}/invites/{invite_id}", status_code=204,
)
async def rescind_invite(
    workspace_id: UUID,
    invite_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> None:
    """Rescind a pending invite. Owner or Admin only. Frees the seat
    immediately (D6.53)."""
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(
        pool, workspace_id, user_uuid, ("owner", "admin"),
    )
    res = await pool.execute(
        "UPDATE workspace_invites SET "
        "  status = 'rescinded', rescinded_at = now() "
        "WHERE id = $1 AND workspace_id = $2 AND status = 'pending'",
        invite_id, workspace_id,
    )
    # asyncpg's execute() returns "UPDATE n" — cheap parse to detect 0.
    if res.endswith(" 0"):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Invite not found, already accepted, or already rescinded.",
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


# ── Wheelhouse billing (Sprint D6.54) ──────────────────────────────────────


@router.post("/{workspace_id}/checkout", response_model=CheckoutResponse)
async def create_workspace_checkout(
    workspace_id: UUID,
    body: CheckoutBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> CheckoutResponse:
    """Create a Stripe Checkout Session for this workspace.

    Owner-only. Used to:
      - Add a payment method during the 30-day trial (status='trialing')
      - Rescue a workspace from card_pending grace
    Cannot be used to switch plans on an active subscription — use the
    billing portal for that. The portal handles subscription updates,
    cancellation, and card replacement; checkout is for the FIRST card
    only.
    """
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(pool, workspace_id, user_uuid, ("owner",))

    try:
        url = await create_workspace_checkout_session(
            workspace_id=workspace_id,
            owner_user_id=current_user.user_id,
            plan=body.plan,
            pool=pool,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return CheckoutResponse(checkout_url=url)


@router.post(
    "/{workspace_id}/billing-portal", response_model=PortalResponse,
)
async def open_workspace_billing_portal(
    workspace_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> PortalResponse:
    """Stripe Billing Portal session URL for this workspace.

    Owner-only. The portal handles cancel, update card, and (if
    enabled in Stripe Dashboard) switch monthly ↔ annual.
    """
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)
    await _require_workspace_role(pool, workspace_id, user_uuid, ("owner",))

    try:
        url = await create_workspace_billing_portal_session(
            workspace_id=workspace_id, pool=pool,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return PortalResponse(portal_url=url)


# ── Workspace state-machine helper exported for chat/dossier writes ────────


async def ensure_workspace_writable(
    pool: asyncpg.Pool, workspace_id: UUID,
) -> None:
    """Raise 403 if the workspace status is read-only.

    Sprint D6.54 — read-only enforcement for `card_pending`,
    `archived`, and `canceled` states. Imported by chat.py,
    conversations.py, and any other write path that operates inside
    workspace context.

    `active` and `trialing` allow writes. `past_due` also allows
    writes — it's a transient dunning state, Stripe will retry the
    card; locking out members during dunning would be customer-hostile.
    """
    ws_status = await pool.fetchval(
        "SELECT status FROM workspaces WHERE id = $1", workspace_id,
    )
    if ws_status is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    if ws_status in ("card_pending", "archived", "canceled"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"Workspace is read-only (status: {ws_status}). "
                "The Owner needs to add a payment method to resume."
            ),
        )


# ── /me/* — caller-scoped invite + view-mode endpoints ─────────────────────
#
# Mounted under a separate router prefix so the path reads naturally:
#   GET    /me/invites           list my pending invites
#   POST   /me/invites/{id}/accept
#   POST   /me/invites/{id}/decline
#   GET    /me/view-mode         which UX shell to render
#
# Both me_router and the workspaces router are registered in main.py.
# These endpoints do NOT require a specific workspace role — they're
# scoped to the caller's identity (email + workspace memberships).
me_router = APIRouter(prefix="/me", tags=["me"])


class ViewModeDTO(BaseModel):
    """The UX shell the frontend should render. Derived state — never
    stored on the user row.

      individual              — no workspaces, regular RegKnots view
      individual_with_workspaces — has workspaces AND a personal sub
                                   (or trial); shows Wheelhouse switcher
      wheelhouse_only         — has workspaces but no personal sub;
                                lands directly in workspace portal,
                                no personal chat surface
    """
    mode: Literal[
        "individual", "individual_with_workspaces", "wheelhouse_only",
    ]
    workspace_count: int
    has_personal_access: bool
    primary_workspace_id: str | None = None
    pending_invite_count: int = 0


@me_router.get("/view-mode", response_model=ViewModeDTO)
async def get_view_mode(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> ViewModeDTO:
    """Return which UX shell the frontend should render for this user.

    `has_personal_access` is true when the user has any path to using
    RegKnots independently of a Wheelhouse — paid sub, active trial,
    admin, or internal flag. The wheelhouse_only mode applies only to
    users whose ONLY access is via a workspace seat.
    """
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)

    row = await pool.fetchrow(
        """
        SELECT
          subscription_tier,
          subscription_status,
          trial_ends_at,
          is_admin,
          is_internal
        FROM users
        WHERE id = $1
        """,
        user_uuid,
    )

    # Trial active → personal access until the trial ends.
    trial_active = (
        row and row["trial_ends_at"]
        and row["trial_ends_at"] > datetime.now(timezone.utc)
    )
    paid_active = (
        row and row["subscription_status"] in ("active", "trialing", "past_due")
        and row["subscription_tier"] not in (None, "free")
    )
    has_personal_access = bool(
        paid_active or trial_active
        or (row and (row["is_admin"] or row["is_internal"]))
    )

    workspaces = await pool.fetch(
        "SELECT workspace_id FROM workspace_members WHERE user_id = $1 "
        "ORDER BY joined_at",
        user_uuid,
    )
    workspace_count = len(workspaces)

    pending_invite_count = await pool.fetchval(
        "SELECT COUNT(*) FROM workspace_invites "
        "WHERE lower(email) = lower($1) "
        "  AND status = 'pending' AND expires_at > now()",
        current_user.email,
    ) or 0

    if workspace_count == 0:
        mode = "individual"
    elif has_personal_access:
        mode = "individual_with_workspaces"
    else:
        mode = "wheelhouse_only"

    return ViewModeDTO(
        mode=mode,
        workspace_count=workspace_count,
        has_personal_access=has_personal_access,
        primary_workspace_id=(
            str(workspaces[0]["workspace_id"]) if workspaces else None
        ),
        pending_invite_count=int(pending_invite_count),
    )


@me_router.get("/invites", response_model=list[WorkspaceInviteDTO])
async def list_my_invites(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> list[WorkspaceInviteDTO]:
    """Pending invites addressed to the caller's email, across all
    workspaces. Used for the post-login banner / invite-claim UX
    (D6.53)."""
    _ensure_feature_enabled()
    await _expire_stale_invites(pool)
    rows = await pool.fetch(
        """
        SELECT wi.id, wi.workspace_id, wi.email, wi.role, wi.status,
               wi.created_at, wi.expires_at,
               w.name AS workspace_name,
               u.email AS inviter_email, u.full_name AS inviter_name
        FROM workspace_invites wi
        JOIN workspaces w ON w.id = wi.workspace_id
        LEFT JOIN users u ON u.id = wi.invited_by_user_id
        WHERE lower(wi.email) = lower($1)
          AND wi.status = 'pending'
          AND wi.expires_at > now()
        ORDER BY wi.created_at DESC
        """,
        current_user.email,
    )
    return [
        _invite_row_to_dto(r, workspace_name=r["workspace_name"])
        for r in rows
    ]


class InviteLookupResponse(BaseModel):
    """Public, unauthenticated lookup so the /invite/<token> landing
    page can show "You've been invited to *F/V Northern Edge*" before
    the user signs in or registers."""
    workspace_name: str
    inviter_name: str | None
    role: Literal["admin", "member"]
    email: str
    expires_at: str
    requires_signup: bool  # True if no RegKnots account exists for `email`


@me_router.get("/invites/lookup/{token}", response_model=InviteLookupResponse)
async def lookup_invite(
    token: str,
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> InviteLookupResponse:
    """Unauthenticated. The /invite/<token> landing page calls this so
    it can render workspace name + role before sending the user
    through register or login. Token is a 32-byte URL-safe random
    string and not feasibly guessable."""
    _ensure_feature_enabled()
    row = await pool.fetchrow(
        """
        SELECT wi.email, wi.role, wi.status, wi.expires_at,
               w.name AS workspace_name,
               u.full_name AS inviter_name
        FROM workspace_invites wi
        JOIN workspaces w ON w.id = wi.workspace_id
        LEFT JOIN users u ON u.id = wi.invited_by_user_id
        WHERE wi.token = $1
        """,
        token,
    )
    if row is None:
        raise HTTPException(404, "Invite not found")
    if row["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Invite is no longer valid (status: {row['status']}).",
        )
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invite has expired.",
        )

    has_account = await pool.fetchval(
        "SELECT 1 FROM users WHERE lower(email) = lower($1)", row["email"],
    )
    return InviteLookupResponse(
        workspace_name=row["workspace_name"],
        inviter_name=row["inviter_name"],
        role=row["role"],
        email=row["email"],
        expires_at=row["expires_at"].isoformat(),
        requires_signup=not bool(has_account),
    )


class AcceptInviteResponse(BaseModel):
    workspace_id: str
    role: Literal["admin", "member"]


@me_router.post(
    "/invites/{invite_id}/accept", response_model=AcceptInviteResponse,
)
async def accept_invite(
    invite_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> AcceptInviteResponse:
    """Accept a pending invite addressed to the signed-in user's email.

    The invite is keyed by id (frontend gets it from /me/invites or
    /me/invites/lookup/{token}). We re-verify the email matches so a
    user can't accept someone else's invite even if they somehow get
    the id.
    """
    _ensure_feature_enabled()
    user_uuid = UUID(current_user.user_id)

    invite = await pool.fetchrow(
        "SELECT workspace_id, email, role, status, expires_at "
        "FROM workspace_invites WHERE id = $1",
        invite_id,
    )
    if invite is None:
        raise HTTPException(404, "Invite not found")
    if invite["email"].lower() != current_user.email.lower():
        # Surface as 404 to avoid leaking the existence of an invite
        # for a different email.
        raise HTTPException(404, "Invite not found")
    if invite["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Invite is no longer valid (status: {invite['status']}).",
        )
    if invite["expires_at"] < datetime.now(timezone.utc):
        await pool.execute(
            "UPDATE workspace_invites SET status = 'expired' WHERE id = $1",
            invite_id,
        )
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Invite has expired.",
        )

    # Re-check seat cap at accept time (someone else may have filled
    # the slot if seats were tight and this invite was pre-issued).
    ws = await pool.fetchrow(
        "SELECT seat_cap FROM workspaces WHERE id = $1", invite["workspace_id"],
    )
    if ws is None:
        raise HTTPException(404, "Workspace no longer exists")
    member_count = await pool.fetchval(
        "SELECT COUNT(*) FROM workspace_members WHERE workspace_id = $1",
        invite["workspace_id"],
    )
    # We DON'T include other pending invites here — accepting THIS
    # invite consumes its reservation, and we want to allow the accept
    # even if the workspace has other pending invites that would push
    # past cap on their own future accepts. (Each accept is checked
    # individually.)
    if member_count >= ws["seat_cap"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Workspace is full. Ask the Owner to remove a member or "
                   "upgrade the plan.",
        )

    async with pool.acquire() as conn:
        async with conn.transaction():
            try:
                await conn.execute(
                    "INSERT INTO workspace_members "
                    "(workspace_id, user_id, role, invited_by_user_id) "
                    "VALUES ($1, $2, $3, NULL)",
                    invite["workspace_id"], user_uuid, invite["role"],
                )
            except asyncpg.UniqueViolationError:
                # Already a member somehow — still mark the invite
                # accepted so the row doesn't haunt the UI.
                pass
            await conn.execute(
                "UPDATE workspace_invites SET "
                "  status = 'accepted', "
                "  accepted_at = now(), "
                "  accepted_by_user_id = $1 "
                "WHERE id = $2",
                user_uuid, invite_id,
            )

    return AcceptInviteResponse(
        workspace_id=str(invite["workspace_id"]),
        role=invite["role"],
    )


@me_router.post("/invites/{invite_id}/decline", status_code=204)
async def decline_invite(
    invite_id: UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> None:
    """Politely decline. Frees the seat. Same email-match check as
    accept to prevent declining someone else's invite."""
    _ensure_feature_enabled()
    invite = await pool.fetchrow(
        "SELECT email, status FROM workspace_invites WHERE id = $1", invite_id,
    )
    if invite is None or invite["email"].lower() != current_user.email.lower():
        raise HTTPException(404, "Invite not found")
    if invite["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=f"Invite is no longer valid (status: {invite['status']}).",
        )
    await pool.execute(
        "UPDATE workspace_invites SET "
        "  status = 'declined', declined_at = now() "
        "WHERE id = $1",
        invite_id,
    )


# ── Auto-claim helper (called from auth.py on register) ───────────────────


async def auto_claim_invites_for_user(
    pool: asyncpg.Pool, user_id: UUID, email: str,
) -> list[UUID]:
    """On registration, automatically accept any still-pending invites
    addressed to the new user's email. Returns the list of workspace_ids
    they were added to, so the caller can surface them in the welcome
    flow.

    This runs in best-effort mode — failures are logged, not raised,
    so a workspace_invites issue can't block account creation."""
    workspace_ids: list[UUID] = []
    try:
        invites = await pool.fetch(
            "SELECT id, workspace_id, role FROM workspace_invites "
            "WHERE lower(email) = lower($1) "
            "  AND status = 'pending' AND expires_at > now()",
            email,
        )
        for inv in invites:
            ws = await pool.fetchrow(
                "SELECT seat_cap FROM workspaces WHERE id = $1",
                inv["workspace_id"],
            )
            if ws is None:
                continue
            members = await pool.fetchval(
                "SELECT COUNT(*) FROM workspace_members "
                "WHERE workspace_id = $1",
                inv["workspace_id"],
            )
            if members >= ws["seat_cap"]:
                # Skip this one but don't kill the loop — other invites
                # may still fit.
                continue
            try:
                async with pool.acquire() as conn:
                    async with conn.transaction():
                        await conn.execute(
                            "INSERT INTO workspace_members "
                            "(workspace_id, user_id, role, invited_by_user_id) "
                            "VALUES ($1, $2, $3, NULL) "
                            "ON CONFLICT DO NOTHING",
                            inv["workspace_id"], user_id, inv["role"],
                        )
                        await conn.execute(
                            "UPDATE workspace_invites SET "
                            "  status = 'accepted', "
                            "  accepted_at = now(), "
                            "  accepted_by_user_id = $1 "
                            "WHERE id = $2",
                            user_id, inv["id"],
                        )
                workspace_ids.append(inv["workspace_id"])
            except Exception as exc:
                logger.warning(
                    "auto_claim invite %s failed: %s", inv["id"], exc,
                )
    except Exception as exc:
        logger.warning("auto_claim_invites_for_user failed: %s", exc)
    return workspace_ids

"""
Vessel CRUD for the authenticated user.

Sprint D6.55 — vessels can now belong to a WORKSPACE (workspace_id set,
read by all members, edited by Owner/Admin) or to a USER (workspace_id
NULL, the legacy personal-vessel behavior). Listing accepts an optional
?workspace_id= query param to surface workspace vessels.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/vessels", tags=["vessels"])

_VALID_ROUTE_TYPES = {"inland", "coastal", "international"}


class VesselListItem(BaseModel):
    id: str
    name: str
    vessel_type: str
    route_types: list[str]
    cargo_types: list[str]
    gross_tonnage: float | None
    subchapter: str | None = None
    inspection_certificate_type: str | None = None
    manning_requirement: str | None = None
    route_limitations: str | None = None
    # D6.55 — populated when the vessel belongs to a workspace.
    workspace_id: str | None = None


async def _require_workspace_member(
    pool, workspace_id: uuid.UUID, user_id: uuid.UUID,
) -> str:
    """Verify caller is a member; return role. 404 if not a member
    (don't leak existence)."""
    role = await pool.fetchval(
        "SELECT role FROM workspace_members "
        "WHERE workspace_id = $1 AND user_id = $2",
        workspace_id, user_id,
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workspace not found",
        )
    return role


@router.get("", response_model=list[VesselListItem])
async def list_vessels(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    workspace_id: Annotated[uuid.UUID | None, Query()] = None,
    pool=Depends(get_pool),
) -> list[VesselListItem]:
    """List vessels.

    - No `workspace_id` → caller's PERSONAL vessels (legacy behavior).
    - `workspace_id=<uuid>` → that workspace's vessels (must be a member).
    """
    async with pool.acquire() as conn:
        if workspace_id is not None:
            await _require_workspace_member(
                conn, workspace_id, uuid.UUID(user.user_id),
            )
            rows = await conn.fetch(
                """
                SELECT id, name, vessel_type, route_types, cargo_types,
                       gross_tonnage, subchapter, inspection_certificate_type,
                       manning_requirement, route_limitations, workspace_id
                FROM vessels
                WHERE workspace_id = $1
                ORDER BY created_at ASC
                """,
                workspace_id,
            )
        else:
            rows = await conn.fetch(
                """
                SELECT id, name, vessel_type, route_types, cargo_types,
                       gross_tonnage, subchapter, inspection_certificate_type,
                       manning_requirement, route_limitations, workspace_id
                FROM vessels
                WHERE user_id = $1 AND workspace_id IS NULL
                ORDER BY created_at ASC
                """,
                uuid.UUID(user.user_id),
            )
    return [
        VesselListItem(
            id=str(r["id"]),
            name=r["name"],
            vessel_type=r["vessel_type"],
            route_types=list(r["route_types"] or []),
            cargo_types=list(r["cargo_types"] or []),
            gross_tonnage=float(r["gross_tonnage"]) if r["gross_tonnage"] is not None else None,
            subchapter=r["subchapter"],
            inspection_certificate_type=r["inspection_certificate_type"],
            manning_requirement=r["manning_requirement"],
            route_limitations=r["route_limitations"],
            workspace_id=str(r["workspace_id"]) if r["workspace_id"] else None,
        )
        for r in rows
    ]


class VesselCreate(BaseModel):
    name: str
    imo_mmsi: str | None = None
    vessel_type: str
    gross_tonnage: float | None = None
    route_types: list[str]
    cargo_types: list[str] = []
    # Extended profile fields (optional — wizard may populate via COI extraction)
    subchapter: str | None = None
    inspection_certificate_type: str | None = None
    manning_requirement: str | None = None
    route_limitations: str | None = None
    # D6.55 — when set, this vessel belongs to a workspace; only
    # Owner/Admin members may create. Personal users / regular members
    # leave this null and create personal vessels (legacy path).
    workspace_id: uuid.UUID | None = None


class VesselResponse(BaseModel):
    id: str
    name: str
    vessel_type: str
    gross_tonnage: float | None
    route_types: list[str]
    cargo_types: list[str]
    workspace_id: str | None = None


def _validate_route_types(route_types: list[str]) -> None:
    if not route_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="route_types must contain at least one value",
        )
    invalid = set(route_types) - _VALID_ROUTE_TYPES
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid route_types: {', '.join(sorted(invalid))}. Must be: {', '.join(sorted(_VALID_ROUTE_TYPES))}",
        )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=VesselResponse)
async def create_vessel(
    body: VesselCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> VesselResponse:
    _validate_route_types(body.route_types)

    # D6.55 — workspace vessel creation requires Owner/Admin role.
    if body.workspace_id is not None:
        async with pool.acquire() as conn:
            role = await _require_workspace_member(
                conn, body.workspace_id, uuid.UUID(user.user_id),
            )
            if role not in ("owner", "admin"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only Owner or Admin can add a workspace vessel.",
                )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO vessels
                (user_id, workspace_id, name, imo_mmsi, vessel_type, gross_tonnage,
                 flag_state, route_types, cargo_types,
                 subchapter, inspection_certificate_type, manning_requirement,
                 route_limitations)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
            RETURNING id, name, vessel_type, gross_tonnage, route_types,
                      cargo_types, workspace_id
            """,
            uuid.UUID(user.user_id),
            body.workspace_id,
            body.name.strip(),
            body.imo_mmsi.strip() if body.imo_mmsi else None,
            body.vessel_type,
            body.gross_tonnage,
            "Unknown",
            body.route_types,
            body.cargo_types,
            body.subchapter,
            body.inspection_certificate_type,
            body.manning_requirement,
            body.route_limitations,
        )

    return VesselResponse(
        id=str(row["id"]),
        name=row["name"],
        vessel_type=row["vessel_type"],
        gross_tonnage=float(row["gross_tonnage"]) if row["gross_tonnage"] is not None else None,
        route_types=list(row["route_types"]),
        cargo_types=list(row["cargo_types"]),
        workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
    )


class VesselUpdate(BaseModel):
    name: str | None = None
    vessel_type: str | None = None
    gross_tonnage: float | None = None
    route_types: list[str] | None = None
    cargo_types: list[str] | None = None
    # Extended profile fields (also populated via COI extraction)
    subchapter: str | None = None
    inspection_certificate_type: str | None = None
    manning_requirement: str | None = None
    route_limitations: str | None = None


async def _authorize_vessel_write(
    conn, vessel_id: uuid.UUID, caller_user_id: uuid.UUID,
) -> None:
    """Caller must own the personal vessel OR be Owner/Admin of the
    workspace owning a workspace vessel. 404 on miss to avoid leaking
    existence."""
    row = await conn.fetchrow(
        "SELECT user_id, workspace_id FROM vessels WHERE id = $1",
        vessel_id,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found",
        )
    if row["workspace_id"] is None:
        # Personal vessel — must be the owner.
        if row["user_id"] != caller_user_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Vessel not found",
            )
        return
    # Workspace vessel — Owner/Admin only.
    role = await conn.fetchval(
        "SELECT role FROM workspace_members "
        "WHERE workspace_id = $1 AND user_id = $2",
        row["workspace_id"], caller_user_id,
    )
    if role is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found",
        )
    if role not in ("owner", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Owner or Admin can edit this workspace vessel.",
        )


@router.put("/{vessel_id}", response_model=VesselResponse)
async def update_vessel(
    vessel_id: str,
    body: VesselUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> VesselResponse:
    if body.route_types is not None:
        _validate_route_types(body.route_types)

    sets: list[str] = []
    params: list[object] = []
    idx = 1
    for field, value in [
        ("name", body.name.strip() if body.name else None),
        ("vessel_type", body.vessel_type),
        ("gross_tonnage", body.gross_tonnage),
        ("route_types", body.route_types),
        ("cargo_types", body.cargo_types),
        ("subchapter", body.subchapter),
        ("inspection_certificate_type", body.inspection_certificate_type),
        ("manning_requirement", body.manning_requirement),
        ("route_limitations", body.route_limitations),
    ]:
        if value is not None:
            sets.append(f"{field} = ${idx}")
            params.append(value)
            idx += 1

    if not sets:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide at least one field to update",
        )

    params.append(uuid.UUID(vessel_id))

    async with pool.acquire() as conn:
        # D6.55 — authorize writes against either personal ownership or
        # workspace Owner/Admin role.
        await _authorize_vessel_write(
            conn, uuid.UUID(vessel_id), uuid.UUID(user.user_id),
        )
        row = await conn.fetchrow(
            f"""
            UPDATE vessels SET {', '.join(sets)}
            WHERE id = ${idx}
            RETURNING id, name, vessel_type, gross_tonnage, route_types,
                      cargo_types, workspace_id
            """,
            *params,
        )

    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    return VesselResponse(
        id=str(row["id"]),
        name=row["name"],
        vessel_type=row["vessel_type"],
        gross_tonnage=float(row["gross_tonnage"]) if row["gross_tonnage"] is not None else None,
        route_types=list(row["route_types"]),
        cargo_types=list(row["cargo_types"]),
        workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
    )


@router.delete("/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vessel(
    vessel_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> None:
    async with pool.acquire() as conn:
        await _authorize_vessel_write(
            conn, uuid.UUID(vessel_id), uuid.UUID(user.user_id),
        )
        await conn.execute(
            "DELETE FROM vessels WHERE id = $1",
            uuid.UUID(vessel_id),
        )

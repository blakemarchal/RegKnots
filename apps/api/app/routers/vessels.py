"""
Vessel CRUD for the authenticated user.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
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


@router.get("", response_model=list[VesselListItem])
async def list_vessels(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> list[VesselListItem]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, vessel_type, route_types, cargo_types, gross_tonnage,
                   subchapter, inspection_certificate_type, manning_requirement,
                   route_limitations
            FROM vessels
            WHERE user_id = $1
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


class VesselResponse(BaseModel):
    id: str
    name: str
    vessel_type: str
    gross_tonnage: float | None
    route_types: list[str]
    cargo_types: list[str]


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

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO vessels
                (user_id, name, imo_mmsi, vessel_type, gross_tonnage,
                 flag_state, route_types, cargo_types)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, name, vessel_type, gross_tonnage, route_types, cargo_types
            """,
            uuid.UUID(user.user_id),
            body.name.strip(),
            body.imo_mmsi.strip() if body.imo_mmsi else None,
            body.vessel_type,
            body.gross_tonnage,
            "Unknown",
            body.route_types,
            body.cargo_types,
        )

    return VesselResponse(
        id=str(row["id"]),
        name=row["name"],
        vessel_type=row["vessel_type"],
        gross_tonnage=float(row["gross_tonnage"]) if row["gross_tonnage"] is not None else None,
        route_types=list(row["route_types"]),
        cargo_types=list(row["cargo_types"]),
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
    params.append(uuid.UUID(user.user_id))

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            f"""
            UPDATE vessels SET {', '.join(sets)}
            WHERE id = ${idx} AND user_id = ${idx + 1}
            RETURNING id, name, vessel_type, gross_tonnage, route_types, cargo_types
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
    )


@router.delete("/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vessel(
    vessel_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> None:
    async with pool.acquire() as conn:
        result = await conn.execute(
            "DELETE FROM vessels WHERE id = $1 AND user_id = $2",
            uuid.UUID(vessel_id),
            uuid.UUID(user.user_id),
        )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

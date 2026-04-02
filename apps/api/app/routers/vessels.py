"""
POST /vessels — create a vessel for the authenticated user.
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
    route_type: str
    cargo_types: list[str]
    gross_tonnage: float | None


@router.get("", response_model=list[VesselListItem])
async def list_vessels(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> list[VesselListItem]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, name, vessel_type, route_type, cargo_types, gross_tonnage
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
            route_type=r["route_type"],
            cargo_types=list(r["cargo_types"] or []),
            gross_tonnage=float(r["gross_tonnage"]) if r["gross_tonnage"] is not None else None,
        )
        for r in rows
    ]


class VesselCreate(BaseModel):
    name: str
    imo_mmsi: str | None = None
    vessel_type: str
    gross_tonnage: float | None = None
    route_type: str
    cargo_types: list[str] = []


class VesselResponse(BaseModel):
    id: str
    name: str
    vessel_type: str
    gross_tonnage: float | None
    route_type: str
    cargo_types: list[str]


@router.post("", status_code=status.HTTP_201_CREATED, response_model=VesselResponse)
async def create_vessel(
    body: VesselCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> VesselResponse:
    if body.route_type not in _VALID_ROUTE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"route_type must be one of: {', '.join(sorted(_VALID_ROUTE_TYPES))}",
        )

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO vessels
                (user_id, name, imo_mmsi, vessel_type, gross_tonnage,
                 flag_state, route_type, cargo_types)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            RETURNING id, name, vessel_type, gross_tonnage, route_type, cargo_types
            """,
            uuid.UUID(user.user_id),
            body.name.strip(),
            body.imo_mmsi.strip() if body.imo_mmsi else None,
            body.vessel_type,
            body.gross_tonnage,
            "Unknown",
            body.route_type,
            body.cargo_types,
        )

    return VesselResponse(
        id=str(row["id"]),
        name=row["name"],
        vessel_type=row["vessel_type"],
        gross_tonnage=float(row["gross_tonnage"]) if row["gross_tonnage"] is not None else None,
        route_type=row["route_type"],
        cargo_types=list(row["cargo_types"]),
    )

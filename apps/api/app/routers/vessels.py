"""
Vessel CRUD for the authenticated user.

Sprint D6.55 — vessels can now belong to a WORKSPACE (workspace_id set,
read by all members, edited by Owner/Admin) or to a USER (workspace_id
NULL, the legacy personal-vessel behavior). Listing accepts an optional
?workspace_id= query param to surface workspace vessels.
"""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

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
    # D6.62 hotfix — surface fields callers (sea-time logger, sea-service
    # letter generator) need for autopopulation. additional_details is
    # the JSONB column where official_number / propulsion / horsepower
    # live for human-edited vessels; latest_coi_extracted is the most-
    # recent COI document's extracted_data so we can pre-fill from a
    # scanned cert without making the user retype.
    additional_details: dict | None = None
    latest_coi_extracted: dict | None = None
    # D6.94 — class society routing. Source distinguishes user-picked
    # ('user') from auto-populated via the IACS lookup table
    # ('iacs_lookup'); the UI shows a "verify" hint when source=
    # iacs_lookup so the mariner can correct an upstream stale value.
    classification_society: str | None = None
    classification_society_source: str | None = None


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
                       manning_requirement, route_limitations, workspace_id,
                       additional_details,
                       classification_society, classification_society_source,
                       (
                         SELECT extracted_data
                         FROM vessel_documents
                         WHERE vessel_id = vessels.id
                           AND document_type = 'coi'
                           AND extraction_status IN ('extracted', 'confirmed')
                         ORDER BY created_at DESC
                         LIMIT 1
                       ) AS latest_coi_extracted
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
                       manning_requirement, route_limitations, workspace_id,
                       additional_details,
                       classification_society, classification_society_source,
                       (
                         SELECT extracted_data
                         FROM vessel_documents
                         WHERE vessel_id = vessels.id
                           AND document_type = 'coi'
                           AND extraction_status IN ('extracted', 'confirmed')
                         ORDER BY created_at DESC
                         LIMIT 1
                       ) AS latest_coi_extracted
                FROM vessels
                WHERE user_id = $1 AND workspace_id IS NULL
                ORDER BY created_at ASC
                """,
                uuid.UUID(user.user_id),
            )
    out: list[VesselListItem] = []
    for r in rows:
        # additional_details + latest_coi_extracted may come back as
        # JSON string (asyncpg returns jsonb as str by default unless
        # decoder is registered). Tolerate both shapes.
        addn = r["additional_details"]
        if isinstance(addn, str):
            try:
                import json as _json
                addn = _json.loads(addn)
            except Exception:
                addn = None
        coi_ex = r["latest_coi_extracted"]
        if isinstance(coi_ex, str):
            try:
                import json as _json
                coi_ex = _json.loads(coi_ex)
            except Exception:
                coi_ex = None

        out.append(VesselListItem(
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
            additional_details=addn if isinstance(addn, dict) else None,
            latest_coi_extracted=coi_ex if isinstance(coi_ex, dict) else None,
            classification_society=r["classification_society"],
            classification_society_source=r["classification_society_source"],
        ))
    return out


_VALID_SOCIETIES = {
    "ABS", "LR", "DNV", "ClassNK", "BV", "KR", "CCS",
    "RINA", "CRS", "IRS", "PRS", "other", "unclassed",
}


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
    # D6.94 — class society. User-picked here is authoritative and
    # locks out the IACS auto-lookup. Leave None to let the create
    # path try the auto-populate from imo_mmsi.
    classification_society: str | None = None
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
    # D6.94 — class society routing.
    classification_society: str | None = None
    classification_society_source: str | None = None


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


def _validate_classification_society(value: str | None) -> None:
    if value is None:
        return
    if value not in _VALID_SOCIETIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"Invalid classification_society: {value}. "
                f"Must be one of: {', '.join(sorted(_VALID_SOCIETIES))}"
            ),
        )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=VesselResponse)
async def create_vessel(
    body: VesselCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> VesselResponse:
    _validate_route_types(body.route_types)
    _validate_classification_society(body.classification_society)

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

    # D6.94 — when the user picks a society explicitly, that's the truth
    # (source='user'). When they leave it blank but provide an IMO, the
    # post-insert auto-populate path will try the IACS lookup.
    initial_society = body.classification_society
    initial_society_source = "user" if initial_society is not None else None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO vessels
                (user_id, workspace_id, name, imo_mmsi, vessel_type, gross_tonnage,
                 flag_state, route_types, cargo_types,
                 subchapter, inspection_certificate_type, manning_requirement,
                 route_limitations,
                 classification_society, classification_society_source)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING id, name, vessel_type, gross_tonnage, route_types,
                      cargo_types, workspace_id,
                      classification_society, classification_society_source
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
            initial_society,
            initial_society_source,
        )

        # D6.94 — IACS auto-populate. Only fires when society is still
        # NULL (user didn't pick) AND IMO is provided. Best-effort: any
        # failure here is logged and swallowed so it doesn't break the
        # vessel-create flow.
        society_after = row["classification_society"]
        society_source_after = row["classification_society_source"]
        if society_after is None and body.imo_mmsi:
            try:
                from app.services.class_society import (
                    auto_populate_classification_society,
                )
                filled = await auto_populate_classification_society(
                    conn, row["id"], body.imo_mmsi,
                )
                if filled:
                    society_after = filled
                    society_source_after = "iacs_lookup"
            except Exception as exc:
                logger.warning(
                    "create_vessel: classification_society auto-populate "
                    "failed for vessel %s: %s: %s",
                    row["id"], type(exc).__name__, str(exc)[:200],
                )

    return VesselResponse(
        id=str(row["id"]),
        name=row["name"],
        vessel_type=row["vessel_type"],
        gross_tonnage=float(row["gross_tonnage"]) if row["gross_tonnage"] is not None else None,
        route_types=list(row["route_types"]),
        cargo_types=list(row["cargo_types"]),
        workspace_id=str(row["workspace_id"]) if row["workspace_id"] else None,
        classification_society=society_after,
        classification_society_source=society_source_after,
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
    # D6.94 — user-facing edit of class society. Setting this stamps
    # source='user', overriding any prior auto-populated value.
    classification_society: str | None = None


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
    _validate_classification_society(body.classification_society)

    sets: list[str] = []
    params: list[object] = []
    idx = 1
    # D6.94 — when the user submits classification_society in an update,
    # stamp source='user' atomically so we don't reopen the lookup-path
    # on the next save.
    if body.classification_society is not None:
        sets.append(f"classification_society_source = ${idx}")
        params.append("user")
        idx += 1
    for field, value in [
        ("name", body.name.strip() if body.name else None),
        ("vessel_type", body.vessel_type),
        ("gross_tonnage", body.gross_tonnage),
        ("route_types", body.route_types),
        ("cargo_types", body.cargo_types),
        ("classification_society", body.classification_society),
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
                      cargo_types, workspace_id,
                      classification_society, classification_society_source
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
        classification_society=row["classification_society"],
        classification_society_source=row["classification_society_source"],
    )


class ClassSocietyLookupResult(BaseModel):
    """Response from the on-demand class-society lookup endpoint."""
    classification_society: str | None
    classification_society_source: str | None
    matched: bool  # True if IACS had a row for this IMO


@router.post(
    "/{vessel_id}/lookup-class-society",
    response_model=ClassSocietyLookupResult,
)
async def lookup_class_society(
    vessel_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> ClassSocietyLookupResult:
    """On-demand IACS class-society lookup for an existing vessel.

    D6.94 — exposed for the existing-user banner that surfaces when a
    user has IMO on file but no classification_society yet. The
    backend hits the iacs_ships_in_class table; if a match exists it
    writes the result with source='iacs_lookup'. Idempotent — never
    overwrites a user-set value.

    Refuses if classification_society is already set (call PUT to
    overwrite). Returns matched=False when no IACS row exists for the
    vessel's IMO; the UI then prompts the user to pick from the dropdown.
    """
    async with pool.acquire() as conn:
        await _authorize_vessel_write(
            conn, uuid.UUID(vessel_id), uuid.UUID(user.user_id),
        )
        existing = await conn.fetchrow(
            "SELECT id, imo_mmsi, classification_society, "
            "       classification_society_source "
            "FROM vessels WHERE id = $1",
            uuid.UUID(vessel_id),
        )
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found",
            )
        if existing["classification_society"] is not None:
            # Already set — return current value, no overwrite.
            return ClassSocietyLookupResult(
                classification_society=existing["classification_society"],
                classification_society_source=existing["classification_society_source"],
                matched=True,
            )

        from app.services.class_society import (
            auto_populate_classification_society,
        )
        filled = await auto_populate_classification_society(
            conn, existing["id"], existing["imo_mmsi"],
        )
        return ClassSocietyLookupResult(
            classification_society=filled,
            classification_society_source="iacs_lookup" if filled else None,
            matched=filled is not None,
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

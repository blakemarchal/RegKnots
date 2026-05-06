"""Sea-time entry tracking endpoints (Sprint D6.62).

Each row is a BLOCK of consecutive sea time (a trip / voyage / contract).
The mariner adds an entry per stretch, then the totals + the existing
sea-service letter generator pull from the same source of truth.

Endpoints:
  POST   /sea-time/entries        — create entry
  GET    /sea-time/entries        — list user's entries (sorted desc)
  GET    /sea-time/entries/{id}   — single entry
  PUT    /sea-time/entries/{id}   — update entry
  DELETE /sea-time/entries/{id}   — delete entry
  GET    /sea-time/totals         — aggregations: lifetime + 3yr / 5yr / by route / by capacity
"""
import logging
import uuid as _uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sea-time", tags=["sea-time"])


# ── Models ────────────────────────────────────────────────────────────────


class SeaTimeEntryBase(BaseModel):
    """Shared fields between create + update + out."""
    vessel_id: str | None = None
    vessel_name: str
    official_number: str | None = None
    vessel_type: str | None = None
    gross_tonnage: float | None = None
    horsepower: str | None = None
    propulsion: str | None = None
    route_type: str | None = None  # "Inland" | "Near-Coastal" | "Coastal" | "Oceans"
    capacity_served: str  # "Master" | "Mate" | "Engineer" | "OS" | "AB" | etc.
    from_date: date
    to_date: date
    days_on_board: int = Field(ge=0)
    employer_name: str | None = None
    employer_signed: bool = False
    notes: str | None = None


class SeaTimeEntryCreate(SeaTimeEntryBase):
    pass


class SeaTimeEntryUpdate(BaseModel):
    """All fields optional for PATCH-style updates."""
    vessel_id: str | None = None
    vessel_name: str | None = None
    official_number: str | None = None
    vessel_type: str | None = None
    gross_tonnage: float | None = None
    horsepower: str | None = None
    propulsion: str | None = None
    route_type: str | None = None
    capacity_served: str | None = None
    from_date: date | None = None
    to_date: date | None = None
    days_on_board: int | None = Field(default=None, ge=0)
    employer_name: str | None = None
    employer_signed: bool | None = None
    notes: str | None = None


class SeaTimeEntryOut(BaseModel):
    id: str
    vessel_id: str | None
    vessel_name: str
    official_number: str | None
    vessel_type: str | None
    gross_tonnage: float | None
    horsepower: str | None
    propulsion: str | None
    route_type: str | None
    capacity_served: str
    from_date: str
    to_date: str
    days_on_board: int
    employer_name: str | None
    employer_signed: bool
    notes: str | None
    created_at: str
    updated_at: str


class SeaTimeTotals(BaseModel):
    """Aggregations powering the UI dashboard + chat reasoning.

    The 3yr/5yr windows match the USCG's "active service" eligibility
    rules for most credential upgrades — those numbers tell a mariner
    if they're cap-eligible right now.
    """
    total_days: int
    days_last_3_years: int
    days_last_5_years: int
    by_route_type: dict[str, int]   # {"Inland": 120, "Coastal": 360, ...}
    by_capacity: dict[str, int]     # {"Master": 200, "Mate": 520}
    entry_count: int
    earliest_date: str | None       # ISO of earliest from_date
    latest_date: str | None         # ISO of latest to_date


# ── Helpers ────────────────────────────────────────────────────────────────


def _row_to_out(r) -> SeaTimeEntryOut:
    return SeaTimeEntryOut(
        id=str(r["id"]),
        vessel_id=str(r["vessel_id"]) if r["vessel_id"] else None,
        vessel_name=r["vessel_name"],
        official_number=r["official_number"],
        vessel_type=r["vessel_type"],
        gross_tonnage=float(r["gross_tonnage"]) if r["gross_tonnage"] is not None else None,
        horsepower=r["horsepower"],
        propulsion=r["propulsion"],
        route_type=r["route_type"],
        capacity_served=r["capacity_served"],
        from_date=r["from_date"].isoformat(),
        to_date=r["to_date"].isoformat(),
        days_on_board=int(r["days_on_board"]),
        employer_name=r["employer_name"],
        employer_signed=bool(r["employer_signed"]),
        notes=r["notes"],
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
    )


def _validate_dates(from_date: date | None, to_date: date | None) -> None:
    if from_date and to_date and to_date < from_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="to_date must be on or after from_date",
        )


# ── CRUD endpoints ─────────────────────────────────────────────────────────


@router.post("/entries", status_code=status.HTTP_201_CREATED, response_model=SeaTimeEntryOut)
async def create_entry(
    body: SeaTimeEntryCreate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SeaTimeEntryOut:
    _validate_dates(body.from_date, body.to_date)
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)
    vessel_uuid = _uuid.UUID(body.vessel_id) if body.vessel_id else None

    row = await pool.fetchrow(
        """
        INSERT INTO sea_time_entries (
            user_id, vessel_id, vessel_name, official_number, vessel_type,
            gross_tonnage, horsepower, propulsion, route_type,
            capacity_served, from_date, to_date, days_on_board,
            employer_name, employer_signed, notes
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16)
        RETURNING *
        """,
        user_uuid, vessel_uuid, body.vessel_name, body.official_number,
        body.vessel_type,
        Decimal(str(body.gross_tonnage)) if body.gross_tonnage is not None else None,
        body.horsepower, body.propulsion, body.route_type,
        body.capacity_served, body.from_date, body.to_date, body.days_on_board,
        body.employer_name, body.employer_signed, body.notes,
    )
    if row is None:
        raise HTTPException(status_code=500, detail="failed to create entry")
    logger.info(
        "sea_time entry created: user=%s vessel=%s days=%d",
        current_user.user_id, body.vessel_name, body.days_on_board,
    )
    return _row_to_out(row)


@router.get("/entries", response_model=list[SeaTimeEntryOut])
async def list_entries(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[SeaTimeEntryOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT * FROM sea_time_entries WHERE user_id = $1 "
        "ORDER BY from_date DESC, created_at DESC",
        _uuid.UUID(current_user.user_id),
    )
    return [_row_to_out(r) for r in rows]


@router.get("/entries/{entry_id}", response_model=SeaTimeEntryOut)
async def get_entry(
    entry_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SeaTimeEntryOut:
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid entry id")
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM sea_time_entries WHERE id = $1 AND user_id = $2",
        eid, _uuid.UUID(current_user.user_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return _row_to_out(row)


@router.put("/entries/{entry_id}", response_model=SeaTimeEntryOut)
async def update_entry(
    entry_id: str,
    body: SeaTimeEntryUpdate,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SeaTimeEntryOut:
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid entry id")

    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    # Pull current row first so we can validate cross-field invariants.
    existing = await pool.fetchrow(
        "SELECT * FROM sea_time_entries WHERE id = $1 AND user_id = $2",
        eid, user_uuid,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail="entry not found")

    # Apply patch
    new_from = body.from_date if body.from_date is not None else existing["from_date"]
    new_to = body.to_date if body.to_date is not None else existing["to_date"]
    _validate_dates(new_from, new_to)

    vessel_uuid = (
        _uuid.UUID(body.vessel_id) if body.vessel_id
        else (None if body.vessel_id == "" else existing["vessel_id"])
    )

    new_gross = (
        Decimal(str(body.gross_tonnage)) if body.gross_tonnage is not None
        else existing["gross_tonnage"]
    )

    row = await pool.fetchrow(
        """
        UPDATE sea_time_entries SET
            vessel_id       = $3,
            vessel_name     = COALESCE($4, vessel_name),
            official_number = COALESCE($5, official_number),
            vessel_type     = COALESCE($6, vessel_type),
            gross_tonnage   = $7,
            horsepower      = COALESCE($8, horsepower),
            propulsion      = COALESCE($9, propulsion),
            route_type      = COALESCE($10, route_type),
            capacity_served = COALESCE($11, capacity_served),
            from_date       = $12,
            to_date         = $13,
            days_on_board   = COALESCE($14, days_on_board),
            employer_name   = COALESCE($15, employer_name),
            employer_signed = COALESCE($16, employer_signed),
            notes           = COALESCE($17, notes)
        WHERE id = $1 AND user_id = $2
        RETURNING *
        """,
        eid, user_uuid, vessel_uuid,
        body.vessel_name, body.official_number, body.vessel_type, new_gross,
        body.horsepower, body.propulsion, body.route_type,
        body.capacity_served, new_from, new_to, body.days_on_board,
        body.employer_name, body.employer_signed, body.notes,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="entry not found")
    return _row_to_out(row)


@router.delete("/entries/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: str,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    try:
        eid = _uuid.UUID(entry_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid entry id")
    pool = await get_pool()
    deleted = await pool.execute(
        "DELETE FROM sea_time_entries WHERE id = $1 AND user_id = $2",
        eid, _uuid.UUID(current_user.user_id),
    )
    # asyncpg returns "DELETE 1" / "DELETE 0"
    if deleted.endswith(" 0"):
        raise HTTPException(status_code=404, detail="entry not found")


# ── Aggregations ───────────────────────────────────────────────────────────


@router.get("/totals", response_model=SeaTimeTotals)
async def totals(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SeaTimeTotals:
    """Aggregations for the dashboard + chat-reasoning context.

    The 3yr / 5yr windows are computed against TODAY (UTC). They count
    only days from each entry that fall within the window, not the
    entry's whole days_on_board (so a 365-day entry that started 4
    years ago still contributes correctly to the 3yr window).
    """
    pool = await get_pool()
    user_uuid = _uuid.UUID(current_user.user_id)

    rows = await pool.fetch(
        "SELECT route_type, capacity_served, from_date, to_date, days_on_board "
        "FROM sea_time_entries WHERE user_id = $1",
        user_uuid,
    )

    today = date.today()
    cutoff_3yr = today - timedelta(days=365 * 3)
    cutoff_5yr = today - timedelta(days=365 * 5)

    total_days = 0
    days_3yr = 0
    days_5yr = 0
    by_route: dict[str, int] = {}
    by_capacity: dict[str, int] = {}
    earliest: date | None = None
    latest: date | None = None

    for r in rows:
        days = int(r["days_on_board"])
        total_days += days
        route = r["route_type"] or "Unspecified"
        cap = r["capacity_served"] or "Unspecified"
        by_route[route] = by_route.get(route, 0) + days
        by_capacity[cap] = by_capacity.get(cap, 0) + days

        # Window calculations: count overlap days, not the full entry.
        f, t = r["from_date"], r["to_date"]
        if earliest is None or f < earliest:
            earliest = f
        if latest is None or t > latest:
            latest = t

        for cutoff, accum_key in ((cutoff_3yr, "3yr"), (cutoff_5yr, "5yr")):
            overlap_start = max(f, cutoff)
            overlap_end = min(t, today)
            if overlap_end >= overlap_start:
                overlap_days = (overlap_end - overlap_start).days + 1
                # Don't exceed the entry's recorded days_on_board (mariners
                # can override down to e.g. account for time off).
                overlap_days = min(overlap_days, days)
                if accum_key == "3yr":
                    days_3yr += overlap_days
                else:
                    days_5yr += overlap_days

    return SeaTimeTotals(
        total_days=total_days,
        days_last_3_years=days_3yr,
        days_last_5_years=days_5yr,
        by_route_type=by_route,
        by_capacity=by_capacity,
        entry_count=len(rows),
        earliest_date=earliest.isoformat() if earliest else None,
        latest_date=latest.isoformat() if latest else None,
    )

"""Compliance / voyage log endpoints.

POST   /logs          — create a log entry
GET    /logs          — list log entries (filterable by vessel, category, date range)
GET    /logs/{id}     — get single log entry
PUT    /logs/{id}     — update a log entry
DELETE /logs/{id}     — delete a log entry
"""

import uuid as _uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/logs", tags=["logs"])

_VALID_CATEGORIES = {
    "safety_drill", "inspection", "maintenance",
    "incident", "navigation", "cargo", "crew",
    "environmental", "psc", "general",
}


class LogCreate(BaseModel):
    vessel_id: str | None = None
    entry_date: date | None = None
    category: str = "general"
    entry: str


class LogUpdate(BaseModel):
    vessel_id: str | None = None
    entry_date: date | None = None
    category: str | None = None
    entry: str | None = None


class LogOut(BaseModel):
    id: str
    vessel_id: str | None
    vessel_name: str | None
    entry_date: str
    category: str
    entry: str
    created_at: str
    updated_at: str


def _row_to_out(r) -> LogOut:
    return LogOut(
        id=str(r["id"]),
        vessel_id=str(r["vessel_id"]) if r["vessel_id"] else None,
        vessel_name=r.get("vessel_name"),
        entry_date=r["entry_date"].isoformat(),
        category=r["category"],
        entry=r["entry"],
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=LogOut)
async def create_log(
    body: LogCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> LogOut:
    if body.category not in _VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}",
        )
    if not body.entry.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Entry text is required",
        )

    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel_id = _uuid.UUID(body.vessel_id) if body.vessel_id else None

    # Verify vessel ownership if provided
    if vessel_id:
        exists = await pool.fetchval(
            "SELECT 1 FROM vessels WHERE id = $1 AND user_id = $2",
            vessel_id, user_id,
        )
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    row = await pool.fetchrow(
        """
        INSERT INTO compliance_logs (user_id, vessel_id, entry_date, category, entry)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING *, NULL AS vessel_name
        """,
        user_id, vessel_id, body.entry_date or date.today(), body.category, body.entry.strip(),
    )

    # Fetch with vessel name
    row = await pool.fetchrow(
        """
        SELECT l.*, v.name AS vessel_name
        FROM compliance_logs l
        LEFT JOIN vessels v ON v.id = l.vessel_id
        WHERE l.id = $1
        """,
        row["id"],
    )
    return _row_to_out(row)


@router.get("", response_model=list[LogOut])
async def list_logs(
    user: Annotated[CurrentUser, Depends(get_current_user)],
    vessel_id: str | None = Query(None),
    category: str | None = Query(None),
    from_date: date | None = Query(None),
    to_date: date | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[LogOut]:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    conditions = ["l.user_id = $1"]
    params: list = [user_id]
    idx = 2

    if vessel_id:
        conditions.append(f"l.vessel_id = ${idx}")
        params.append(_uuid.UUID(vessel_id))
        idx += 1
    if category:
        conditions.append(f"l.category = ${idx}")
        params.append(category)
        idx += 1
    if from_date:
        conditions.append(f"l.entry_date >= ${idx}")
        params.append(from_date)
        idx += 1
    if to_date:
        conditions.append(f"l.entry_date <= ${idx}")
        params.append(to_date)
        idx += 1

    where = " AND ".join(conditions)
    params.extend([limit, offset])

    rows = await pool.fetch(
        f"""
        SELECT l.*, v.name AS vessel_name
        FROM compliance_logs l
        LEFT JOIN vessels v ON v.id = l.vessel_id
        WHERE {where}
        ORDER BY l.entry_date DESC, l.created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
    )
    return [_row_to_out(r) for r in rows]


@router.get("/{log_id}", response_model=LogOut)
async def get_log(
    log_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> LogOut:
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        SELECT l.*, v.name AS vessel_name
        FROM compliance_logs l
        LEFT JOIN vessels v ON v.id = l.vessel_id
        WHERE l.id = $1 AND l.user_id = $2
        """,
        log_id, _uuid.UUID(user.user_id),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log entry not found")
    return _row_to_out(row)


@router.put("/{log_id}", response_model=LogOut)
async def update_log(
    log_id: _uuid.UUID,
    body: LogUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> LogOut:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    existing = await pool.fetchrow(
        "SELECT * FROM compliance_logs WHERE id = $1 AND user_id = $2",
        log_id, user_id,
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log entry not found")

    if body.category and body.category not in _VALID_CATEGORIES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid category. Must be one of: {', '.join(sorted(_VALID_CATEGORIES))}",
        )

    sets: list[str] = []
    params: list = []
    idx = 1
    updates = body.model_dump(exclude_unset=True)

    if "vessel_id" in updates:
        v = updates["vessel_id"]
        if v:
            vid = _uuid.UUID(v)
            exists = await pool.fetchval(
                "SELECT 1 FROM vessels WHERE id = $1 AND user_id = $2", vid, user_id,
            )
            if not exists:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")
            sets.append(f"vessel_id = ${idx}")
            params.append(vid)
        else:
            sets.append(f"vessel_id = NULL")
        idx += 1 if v else idx

    for field in ("entry_date", "category"):
        if field in updates and updates[field] is not None:
            sets.append(f"{field} = ${idx}")
            params.append(updates[field])
            idx += 1

    if "entry" in updates and updates["entry"] is not None:
        sets.append(f"entry = ${idx}")
        params.append(updates["entry"].strip())
        idx += 1

    if not sets:
        row = await pool.fetchrow(
            """
            SELECT l.*, v.name AS vessel_name FROM compliance_logs l
            LEFT JOIN vessels v ON v.id = l.vessel_id WHERE l.id = $1
            """,
            log_id,
        )
        return _row_to_out(row)

    params.extend([log_id, user_id])
    sql = f"UPDATE compliance_logs SET {', '.join(sets)} WHERE id = ${idx} AND user_id = ${idx + 1}"
    await pool.execute(sql, *params)

    row = await pool.fetchrow(
        """
        SELECT l.*, v.name AS vessel_name FROM compliance_logs l
        LEFT JOIN vessels v ON v.id = l.vessel_id WHERE l.id = $1
        """,
        log_id,
    )
    return _row_to_out(row)


@router.delete("/{log_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_log(
    log_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM compliance_logs WHERE id = $1 AND user_id = $2",
        log_id, _uuid.UUID(user.user_id),
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log entry not found")

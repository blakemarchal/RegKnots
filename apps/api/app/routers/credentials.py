"""Personal credential tracking endpoints.

POST   /credentials                — create a credential
GET    /credentials                — list all user credentials
GET    /credentials/{id}           — get single credential
PUT    /credentials/{id}           — update a credential
DELETE /credentials/{id}           — delete a credential
"""

import uuid as _uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/credentials", tags=["credentials"])

_VALID_TYPES = {"mmc", "stcw", "medical", "twic", "other"}


class CredentialCreate(BaseModel):
    credential_type: str
    title: str
    credential_number: str | None = None
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class CredentialUpdate(BaseModel):
    credential_type: str | None = None
    title: str | None = None
    credential_number: str | None = None
    issuing_authority: str | None = None
    issue_date: date | None = None
    expiry_date: date | None = None
    notes: str | None = None


class CredentialOut(BaseModel):
    id: str
    credential_type: str
    title: str
    credential_number: str | None
    issuing_authority: str | None
    issue_date: str | None
    expiry_date: str | None
    notes: str | None
    created_at: str
    updated_at: str


def _row_to_out(r) -> CredentialOut:
    return CredentialOut(
        id=str(r["id"]),
        credential_type=r["credential_type"],
        title=r["title"],
        credential_number=r["credential_number"],
        issuing_authority=r["issuing_authority"],
        issue_date=r["issue_date"].isoformat() if r["issue_date"] else None,
        expiry_date=r["expiry_date"].isoformat() if r["expiry_date"] else None,
        notes=r["notes"],
        created_at=r["created_at"].isoformat(),
        updated_at=r["updated_at"].isoformat(),
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CredentialOut)
async def create_credential(
    body: CredentialCreate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CredentialOut:
    if body.credential_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid credential_type. Must be one of: {', '.join(sorted(_VALID_TYPES))}",
        )
    pool = await get_pool()
    row = await pool.fetchrow(
        """
        INSERT INTO user_credentials
            (user_id, credential_type, title, credential_number,
             issuing_authority, issue_date, expiry_date, notes)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING *
        """,
        _uuid.UUID(user.user_id),
        body.credential_type,
        body.title.strip(),
        body.credential_number,
        body.issuing_authority,
        body.issue_date,
        body.expiry_date,
        body.notes,
    )
    return _row_to_out(row)


@router.get("", response_model=list[CredentialOut])
async def list_credentials(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[CredentialOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT * FROM user_credentials
        WHERE user_id = $1
        ORDER BY
            CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END,
            expiry_date ASC,
            created_at DESC
        """,
        _uuid.UUID(user.user_id),
    )
    return [_row_to_out(r) for r in rows]


@router.get("/{credential_id}", response_model=CredentialOut)
async def get_credential(
    credential_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CredentialOut:
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM user_credentials WHERE id = $1 AND user_id = $2",
        credential_id, _uuid.UUID(user.user_id),
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return _row_to_out(row)


@router.put("/{credential_id}", response_model=CredentialOut)
async def update_credential(
    credential_id: _uuid.UUID,
    body: CredentialUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> CredentialOut:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    existing = await pool.fetchrow(
        "SELECT * FROM user_credentials WHERE id = $1 AND user_id = $2",
        credential_id, user_id,
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    if body.credential_type and body.credential_type not in _VALID_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid credential_type. Must be one of: {', '.join(sorted(_VALID_TYPES))}",
        )

    # Build dynamic update
    sets: list[str] = []
    params: list = []
    idx = 1
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        if field == "title" and isinstance(value, str):
            value = value.strip()
        sets.append(f"{field} = ${idx}")
        params.append(value)
        idx += 1

    if not sets:
        return _row_to_out(existing)

    # Reset reminder flags if expiry_date changed
    if "expiry_date" in updates:
        sets.append(f"reminder_sent_90 = FALSE")
        sets.append(f"reminder_sent_30 = FALSE")
        sets.append(f"reminder_sent_7 = FALSE")

    params.append(credential_id)
    params.append(user_id)
    sql = f"UPDATE user_credentials SET {', '.join(sets)} WHERE id = ${idx} AND user_id = ${idx + 1} RETURNING *"
    row = await pool.fetchrow(sql, *params)
    return _row_to_out(row)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_credential(
    credential_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    result = await pool.execute(
        "DELETE FROM user_credentials WHERE id = $1 AND user_id = $2",
        credential_id, _uuid.UUID(user.user_id),
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

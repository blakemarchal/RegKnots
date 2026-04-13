"""Personal credential tracking endpoints.

POST   /credentials                      — create a credential
GET    /credentials                      — list all user credentials
GET    /credentials/{id}                 — get single credential
PUT    /credentials/{id}                 — update a credential
DELETE /credentials/{id}                 — delete a credential
POST   /credentials/extract-from-photo   — extract credential data from a photo
"""

import base64
import io
import json
import logging
import uuid as _uuid
from datetime import date
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

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


# ── Photo extraction ──────────────────────────────────────────────────────

_CREDENTIAL_EXTRACTION_PROMPT = """\
You are analyzing a photo of a U.S. maritime personal credential document.
This could be a Merchant Mariner Credential (MMC), STCW endorsement,
medical certificate, TWIC card, or other mariner credential.

Extract the following fields from the image:
- credential_type: one of "mmc", "stcw", "medical", "twic", or "other"
- title: the credential title or endorsement name (e.g., "Master 1600 GRT", "STCW II/1", "Medical Certificate")
- credential_number: the credential/document number if visible
- issuing_authority: the issuing authority (e.g., "USCG NMC", "USCG", "TSA")
- issue_date: date issued in YYYY-MM-DD format if visible
- expiry_date: expiration date in YYYY-MM-DD format if visible

Return ONLY a JSON object with these fields. Use null for fields you cannot identify.
Do not include any explanation or markdown — just the JSON."""

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}


class CredentialExtraction(BaseModel):
    credential_type: str | None = None
    title: str | None = None
    credential_number: str | None = None
    issuing_authority: str | None = None
    issue_date: str | None = None
    expiry_date: str | None = None


@router.post("/extract-from-photo", response_model=CredentialExtraction)
async def extract_credential_from_photo(
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> CredentialExtraction:
    """Extract credential data from a photo using Claude Vision."""
    content_type = file.content_type or ""
    if content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type: {content_type}. Allowed: JPEG, PNG, WebP, PDF.",
        )

    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File too large. Maximum size is 10 MB.",
        )

    # Build vision content blocks
    if content_type == "application/pdf":
        from pdf2image import convert_from_bytes

        images = convert_from_bytes(content, first_page=1, last_page=2, dpi=200)
        content_blocks: list[dict] = []
        for img in images:
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
            content_blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": "image/png", "data": b64},
            })
        content_blocks.append({"type": "text", "text": _CREDENTIAL_EXTRACTION_PROMPT})
    else:
        b64 = base64.b64encode(content).decode("utf-8")
        content_blocks = [
            {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}},
            {"type": "text", "text": _CREDENTIAL_EXTRACTION_PROMPT},
        ]

    try:
        anthropic_client: AsyncAnthropic = request.app.state.anthropic
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": content_blocks}],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        extracted = json.loads(text.strip())

        logger.info("Credential extraction complete: user=%s fields=%s", current_user.user_id, list(extracted.keys()))
        return CredentialExtraction(**{k: v for k, v in extracted.items() if v != "null" and v is not None})

    except Exception:
        logger.exception("Credential extraction failed")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not extract data from this document. Try a clearer photo.",
        )

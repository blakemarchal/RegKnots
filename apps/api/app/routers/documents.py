"""
Vessel document upload, extraction, and management.

POST   /vessels/{vessel_id}/documents              — upload + extract
POST   /vessels/{vessel_id}/documents/{doc_id}/confirm — confirm extracted data
GET    /vessels/{vessel_id}/documents              — list documents
DELETE /vessels/{vessel_id}/documents/{doc_id}     — delete document
"""

import base64
import json
import logging
import os
import uuid as _uuid
from pathlib import Path
from typing import Annotated

import asyncpg
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.config import settings
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vessels", tags=["documents"])

_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}

_EXTRACTION_PROMPT = """\
You are analyzing a U.S. maritime vessel document. Extract all structured data from this image.

If this is a Certificate of Inspection (COI), extract:
- vessel_name: official vessel name
- official_number: USCG official number
- imo_number: IMO number if present
- call_sign: radio call sign if present
- vessel_type: type of vessel
- subchapter: USCG subchapter (T, K, H, I, R, etc.)
- gross_tonnage: gross tonnage
- route: authorized route (inland, coastwise, near-coastal, oceans, Great Lakes, etc.)
- route_limitations: any specific route limitations or restrictions
- max_persons: maximum persons allowed
- max_passengers: maximum passengers if applicable
- manning_requirement: minimum manning requirements
- hull_material: hull material (steel, aluminum, FRP, wood)
- keel_date: keel laying date if shown
- inspection_date: date of last inspection
- expiration_date: certificate expiration date
- issuing_office: USCG office that issued the certificate
- conditions_of_operation: any conditions or restrictions noted
- lifesaving_equipment: summary of required lifesaving equipment
- fire_equipment: summary of required fire equipment

For any other maritime document, extract all identifiable fields.

Return ONLY a JSON object with the extracted fields. Use null for fields you cannot identify.
Do not include any explanation or markdown — just the JSON."""


# ── Models ──────────────────────────────────────────────────────────────────


class DocumentOut(BaseModel):
    id: str
    vessel_id: str
    document_type: str
    filename: str
    file_size: int | None
    mime_type: str | None
    extracted_data: dict
    extraction_status: str
    created_at: str


class ConfirmBody(BaseModel):
    corrections: dict = {}


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _verify_vessel_ownership(
    vessel_id: _uuid.UUID, user_id: _uuid.UUID, pool: asyncpg.Pool,
) -> None:
    """Raise 404 if vessel doesn't exist or user doesn't own it."""
    exists = await pool.fetchval(
        "SELECT 1 FROM vessels WHERE id = $1 AND user_id = $2",
        vessel_id, user_id,
    )
    if not exists:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")


async def _extract_with_vision(
    file_path: str, mime_type: str, client: AsyncAnthropic,
) -> dict:
    """Send an image to Claude Vision for structured data extraction."""
    with open(file_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # For PDFs, use the document source type
    if mime_type == "application/pdf":
        content_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": image_data,
            },
        }
    else:
        content_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": mime_type,
                "data": image_data,
            },
        }

    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": [
                content_block,
                {"type": "text", "text": _EXTRACTION_PROMPT},
            ],
        }],
    )

    text = response.content[0].text.strip()
    # Strip markdown fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    return json.loads(text)


def _row_to_doc(r) -> DocumentOut:
    extracted = r["extracted_data"]
    if isinstance(extracted, str):
        extracted = json.loads(extracted)
    elif extracted is None:
        extracted = {}
    return DocumentOut(
        id=str(r["id"]),
        vessel_id=str(r["vessel_id"]),
        document_type=r["document_type"],
        filename=r["filename"],
        file_size=r["file_size"],
        mime_type=r["mime_type"],
        extracted_data=extracted,
        extraction_status=r["extraction_status"],
        created_at=r["created_at"].isoformat(),
    )


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/{vessel_id}/documents", status_code=status.HTTP_201_CREATED)
async def upload_document(
    vessel_id: _uuid.UUID,
    request: Request,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
    file: UploadFile = File(...),
    document_type: str = Form("coi"),
) -> DocumentOut:
    user_id = _uuid.UUID(current_user.user_id)
    await _verify_vessel_ownership(vessel_id, user_id, pool)

    # Validate MIME type
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported file type: {file.content_type}. Allowed: JPEG, PNG, WebP, PDF.",
        )

    # Validate document_type
    valid_doc_types = {"coi", "safety_equipment", "safety_construction", "safety_radio", "isps", "ism", "other"}
    if document_type not in valid_doc_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid document_type: {document_type}",
        )

    # Read and validate file size
    content = await file.read()
    if len(content) > _MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File too large. Maximum size is 10 MB.",
        )

    # Determine file extension from MIME type
    ext_map = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "application/pdf": ".pdf",
    }
    ext = ext_map.get(file.content_type, ".bin")

    # Save to disk
    file_id = _uuid.uuid4()
    dir_path = Path(settings.upload_dir) / str(vessel_id)
    dir_path.mkdir(parents=True, exist_ok=True)
    file_path = dir_path / f"{file_id}{ext}"
    file_path.write_bytes(content)

    logger.info(
        "Saved document upload: vessel=%s type=%s size=%d path=%s",
        vessel_id, document_type, len(content), file_path,
    )

    # Create DB record
    row = await pool.fetchrow(
        """
        INSERT INTO vessel_documents
            (vessel_id, user_id, document_type, filename, file_path, file_size, mime_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        vessel_id,
        user_id,
        document_type,
        file.filename or "upload",
        str(file_path),
        len(content),
        file.content_type,
    )
    doc_id = row["id"]

    # Run extraction
    extraction_status = "pending"
    extracted: dict = {}
    try:
        anthropic_client: AsyncAnthropic = request.app.state.anthropic
        extracted = await _extract_with_vision(str(file_path), file.content_type, anthropic_client)
        extraction_status = "extracted"
        logger.info(
            "Extraction complete: doc=%s fields=%s",
            doc_id, list(extracted.keys()),
        )
    except Exception:
        logger.exception("Extraction failed for document %s", doc_id)
        extraction_status = "failed"

    # Update record with extraction results
    await pool.execute(
        """
        UPDATE vessel_documents
        SET extracted_data = $1, extraction_status = $2
        WHERE id = $3
        """,
        json.dumps(extracted),
        extraction_status,
        doc_id,
    )

    # Re-fetch to get updated row
    row = await pool.fetchrow("SELECT * FROM vessel_documents WHERE id = $1", doc_id)
    return _row_to_doc(row)


@router.post("/{vessel_id}/documents/{doc_id}/confirm")
async def confirm_document(
    vessel_id: _uuid.UUID,
    doc_id: _uuid.UUID,
    body: ConfirmBody,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> DocumentOut:
    user_id = _uuid.UUID(current_user.user_id)
    await _verify_vessel_ownership(vessel_id, user_id, pool)

    # Fetch the document
    row = await pool.fetchrow(
        "SELECT * FROM vessel_documents WHERE id = $1 AND vessel_id = $2",
        doc_id, vessel_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Merge corrections into extracted data
    raw = row["extracted_data"]
    if isinstance(raw, str):
        extracted = json.loads(raw)
    elif raw is None:
        extracted = {}
    else:
        extracted = dict(raw)

    if body.corrections:
        extracted.update(body.corrections)

    # Update document status
    await pool.execute(
        """
        UPDATE vessel_documents
        SET extracted_data = $1, extraction_status = 'confirmed'
        WHERE id = $2
        """,
        json.dumps(extracted),
        doc_id,
    )

    # Apply extracted data to vessel profile
    await _apply_document_to_vessel(pool, vessel_id, extracted)

    row = await pool.fetchrow("SELECT * FROM vessel_documents WHERE id = $1", doc_id)
    return _row_to_doc(row)


async def _apply_document_to_vessel(
    pool: asyncpg.Pool, vessel_id: _uuid.UUID, extracted: dict,
) -> None:
    """Map confirmed document data back to the vessels table."""
    sets: list[str] = []
    params: list = []
    idx = 1

    # Direct column mappings
    field_map = {
        "subchapter": "subchapter",
        "manning_requirement": "manning_requirement",
        "route_limitations": "route_limitations",
        "inspection_certificate_type": "inspection_certificate_type",
    }
    for ext_key, col in field_map.items():
        val = extracted.get(ext_key)
        if val and val != "null":
            sets.append(f"{col} = ${idx}")
            params.append(str(val))
            idx += 1

    # Gross tonnage — only if not already set
    gt = extracted.get("gross_tonnage")
    if gt and gt != "null":
        try:
            gt_val = float(str(gt).replace(",", ""))
            sets.append(f"gross_tonnage = COALESCE(gross_tonnage, ${idx})")
            params.append(gt_val)
            idx += 1
        except (ValueError, TypeError):
            pass

    # Route → route_types
    route = extracted.get("route")
    if route and route != "null":
        route_str = str(route).lower()
        route_types: list[str] = []
        if any(k in route_str for k in ("inland", "river", "lake", "great lakes")):
            route_types.append("inland")
        if any(k in route_str for k in ("coast", "near-coastal", "coastwise")):
            route_types.append("coastal")
        if any(k in route_str for k in ("ocean", "international", "unlimited")):
            route_types.append("international")
        if route_types:
            sets.append(f"route_types = ${idx}")
            params.append(route_types)
            idx += 1

    # Store rich fields in additional_details JSONB
    rich_keys = [
        "official_number", "imo_number", "call_sign", "hull_material",
        "keel_date", "inspection_date", "expiration_date", "issuing_office",
        "max_persons", "max_passengers", "conditions_of_operation",
        "lifesaving_equipment", "fire_equipment",
    ]
    additional = {}
    for k in rich_keys:
        v = extracted.get(k)
        if v and v != "null" and str(v).strip():
            additional[k] = str(v)

    if additional:
        sets.append(f"additional_details = COALESCE(additional_details, '{{}}'::jsonb) || ${idx}::jsonb")
        params.append(json.dumps(additional))
        idx += 1

    if sets:
        sets.append("profile_enriched_at = NOW()")
        params.append(vessel_id)
        sql = f"UPDATE vessels SET {', '.join(sets)} WHERE id = ${idx}"
        await pool.execute(sql, *params)
        logger.info("Applied document data to vessel %s: %d fields updated", vessel_id, len(sets) - 1)


@router.get("/{vessel_id}/documents")
async def list_documents(
    vessel_id: _uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> list[DocumentOut]:
    user_id = _uuid.UUID(current_user.user_id)
    await _verify_vessel_ownership(vessel_id, user_id, pool)

    rows = await pool.fetch(
        """
        SELECT * FROM vessel_documents
        WHERE vessel_id = $1
        ORDER BY created_at DESC
        """,
        vessel_id,
    )
    return [_row_to_doc(r) for r in rows]


@router.delete("/{vessel_id}/documents/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    vessel_id: _uuid.UUID,
    doc_id: _uuid.UUID,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    pool: Annotated[asyncpg.Pool, Depends(get_pool)],
) -> None:
    user_id = _uuid.UUID(current_user.user_id)
    await _verify_vessel_ownership(vessel_id, user_id, pool)

    row = await pool.fetchrow(
        "SELECT file_path FROM vessel_documents WHERE id = $1 AND vessel_id = $2",
        doc_id, vessel_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    # Delete file from disk
    try:
        fp = Path(row["file_path"])
        if fp.exists():
            fp.unlink()
            logger.info("Deleted file: %s", fp)
    except Exception:
        logger.exception("Failed to delete file: %s", row["file_path"])

    await pool.execute("DELETE FROM vessel_documents WHERE id = $1", doc_id)

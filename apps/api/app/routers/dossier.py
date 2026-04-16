"""Vessel dossier — aggregated vessel intelligence view.

GET /dossier/{vessel_id} — everything RegKnot knows about a vessel
"""

import json
import uuid as _uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/dossier", tags=["dossier"])


class VesselProfile(BaseModel):
    name: str
    vessel_type: str
    gross_tonnage: float | None
    route_types: list[str]
    flag_state: str | None
    subchapter: str | None
    manning_requirement: str | None
    route_limitations: str | None
    inspection_certificate_type: str | None
    official_number: str | None
    imo_number: str | None
    call_sign: str | None
    hull_material: str | None
    expiration_date: str | None
    max_persons: str | None
    lifesaving_equipment: str | None
    fire_equipment: str | None
    conditions_of_operation: str | None
    profile_enriched_at: str | None


class CredentialSummary(BaseModel):
    id: str
    credential_type: str
    title: str
    expiry_date: str | None
    days_remaining: int | None


class DocumentSummary(BaseModel):
    id: str
    document_type: str
    filename: str
    extraction_status: str
    created_at: str


class LogSummary(BaseModel):
    total_entries: int
    categories: dict[str, int]
    latest_entry_date: str | None


class ChecklistSummary(BaseModel):
    exists: bool
    item_count: int
    checked_count: int
    generated_at: str | None
    user_edits: int


class ChatSummary(BaseModel):
    total_conversations: int
    total_messages: int
    last_active: str | None
    top_topics: list[str]


class VesselDossier(BaseModel):
    vessel_id: str
    profile: VesselProfile
    credentials: list[CredentialSummary]
    documents: list[DocumentSummary]
    compliance_log: LogSummary
    psc_checklist: ChecklistSummary
    chat_activity: ChatSummary


@router.get("/{vessel_id}", response_model=VesselDossier)
async def get_vessel_dossier(
    vessel_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> VesselDossier:
    """Aggregate everything RegKnot knows about a vessel into one view."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    # ── Vessel profile ────────────────────────────────────────────────
    vessel = await pool.fetchrow(
        "SELECT * FROM vessels WHERE id = $1 AND user_id = $2",
        vessel_id, user_id,
    )
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    additional = vessel.get("additional_details") or {}
    if isinstance(additional, str):
        additional = json.loads(additional)

    profile = VesselProfile(
        name=vessel["name"],
        vessel_type=vessel["vessel_type"],
        gross_tonnage=float(vessel["gross_tonnage"]) if vessel.get("gross_tonnage") else None,
        route_types=list(vessel.get("route_types") or []),
        flag_state=vessel.get("flag_state"),
        subchapter=vessel.get("subchapter"),
        manning_requirement=vessel.get("manning_requirement"),
        route_limitations=vessel.get("route_limitations"),
        inspection_certificate_type=vessel.get("inspection_certificate_type"),
        official_number=additional.get("official_number"),
        imo_number=additional.get("imo_number"),
        call_sign=additional.get("call_sign"),
        hull_material=additional.get("hull_material"),
        expiration_date=additional.get("expiration_date"),
        max_persons=additional.get("max_persons"),
        lifesaving_equipment=additional.get("lifesaving_equipment"),
        fire_equipment=additional.get("fire_equipment"),
        conditions_of_operation=additional.get("conditions_of_operation"),
        profile_enriched_at=vessel["profile_enriched_at"].isoformat() if vessel.get("profile_enriched_at") else None,
    )

    # ── User credentials ──────────────────────────────────────────────
    cred_rows = await pool.fetch(
        """
        SELECT id, credential_type, title, expiry_date
        FROM user_credentials
        WHERE user_id = $1
        ORDER BY expiry_date ASC NULLS LAST
        """,
        user_id,
    )
    today = date.today()
    credentials = [
        CredentialSummary(
            id=str(r["id"]),
            credential_type=r["credential_type"],
            title=r["title"],
            expiry_date=r["expiry_date"].isoformat() if r["expiry_date"] else None,
            days_remaining=(r["expiry_date"] - today).days if r["expiry_date"] else None,
        )
        for r in cred_rows
    ]

    # ── Vessel documents ──────────────────────────────────────────────
    doc_rows = await pool.fetch(
        """
        SELECT id, document_type, filename, extraction_status, created_at
        FROM vessel_documents
        WHERE vessel_id = $1
        ORDER BY created_at DESC
        """,
        vessel_id,
    )
    documents = [
        DocumentSummary(
            id=str(r["id"]),
            document_type=r["document_type"],
            filename=r["filename"],
            extraction_status=r["extraction_status"],
            created_at=r["created_at"].isoformat(),
        )
        for r in doc_rows
    ]

    # ── Compliance log summary ────────────────────────────────────────
    log_rows = await pool.fetch(
        """
        SELECT category, COUNT(*) AS cnt, MAX(entry_date) AS latest
        FROM compliance_logs
        WHERE user_id = $1 AND vessel_id = $2
        GROUP BY category
        """,
        user_id, vessel_id,
    )
    log_total = sum(r["cnt"] for r in log_rows)
    log_categories = {r["category"]: r["cnt"] for r in log_rows}
    log_latest = max((r["latest"] for r in log_rows), default=None)
    compliance_log = LogSummary(
        total_entries=log_total,
        categories=log_categories,
        latest_entry_date=log_latest.isoformat() if log_latest else None,
    )

    # ── PSC checklist summary ─────────────────────────────────────────
    cl_row = await pool.fetchrow(
        """
        SELECT items, checked_indices, generated_at
        FROM psc_checklists
        WHERE user_id = $1 AND vessel_id = $2
        """,
        user_id, vessel_id,
    )
    edit_count = await pool.fetchval(
        "SELECT COUNT(*) FROM checklist_feedback WHERE user_id = $1 AND vessel_id = $2",
        user_id, vessel_id,
    )
    if cl_row:
        items_raw = cl_row["items"]
        if isinstance(items_raw, str):
            items_raw = json.loads(items_raw)
        psc_checklist = ChecklistSummary(
            exists=True,
            item_count=len(items_raw) if isinstance(items_raw, list) else 0,
            checked_count=len(cl_row["checked_indices"] or []),
            generated_at=cl_row["generated_at"].isoformat() if cl_row["generated_at"] else None,
            user_edits=edit_count or 0,
        )
    else:
        psc_checklist = ChecklistSummary(
            exists=False, item_count=0, checked_count=0,
            generated_at=None, user_edits=edit_count or 0,
        )

    # ── Chat activity summary ─────────────────────────────────────────
    chat_stats = await pool.fetchrow(
        """
        SELECT
            COUNT(DISTINCT c.id) AS total_conversations,
            COUNT(m.id) AS total_messages,
            MAX(m.created_at) AS last_active
        FROM conversations c
        LEFT JOIN messages m ON m.conversation_id = c.id
        WHERE c.user_id = $1 AND c.vessel_id = $2
        """,
        user_id, vessel_id,
    )
    topic_rows = await pool.fetch(
        """
        SELECT title FROM conversations
        WHERE user_id = $1 AND vessel_id = $2 AND title IS NOT NULL
        ORDER BY created_at DESC
        LIMIT 5
        """,
        user_id, vessel_id,
    )
    chat_activity = ChatSummary(
        total_conversations=chat_stats["total_conversations"] or 0,
        total_messages=chat_stats["total_messages"] or 0,
        last_active=chat_stats["last_active"].isoformat() if chat_stats["last_active"] else None,
        top_topics=[r["title"] for r in topic_rows],
    )

    return VesselDossier(
        vessel_id=str(vessel_id),
        profile=profile,
        credentials=credentials,
        documents=documents,
        compliance_log=compliance_log,
        psc_checklist=psc_checklist,
        chat_activity=chat_activity,
    )

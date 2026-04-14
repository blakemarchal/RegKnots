"""Compliance summary PDF export and shareable vessel profile.

GET  /export/vessel/{vessel_id}/pdf     — download compliance summary PDF
POST /export/vessel/{vessel_id}/share   — generate/get share token
GET  /export/shared/{share_token}       — public shareable vessel profile
"""

import io
import json
import logging
import secrets
import uuid as _uuid
from datetime import datetime, timezone
from typing import Annotated

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/export", tags=["export"])


# ── Helpers ────────────────────────────────────────────────────────────────


async def _load_vessel_profile(
    pool: asyncpg.Pool, vessel_id: _uuid.UUID, user_id: _uuid.UUID,
) -> dict:
    """Load full vessel profile. Raises 404 if not found or not owned."""
    row = await pool.fetchrow(
        "SELECT * FROM vessels WHERE id = $1 AND user_id = $2",
        vessel_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")
    return dict(row)


async def _load_vessel_by_token(pool: asyncpg.Pool, token: str) -> dict | None:
    """Load vessel by share token (public access)."""
    row = await pool.fetchrow(
        "SELECT * FROM vessels WHERE share_token = $1", token,
    )
    return dict(row) if row else None


def _vessel_to_profile(vessel: dict) -> dict:
    """Convert a vessel DB row to a clean profile dict."""
    additional = vessel.get("additional_details") or {}
    if isinstance(additional, str):
        additional = json.loads(additional)

    return {
        "name": vessel["name"],
        "vessel_type": vessel["vessel_type"],
        "gross_tonnage": float(vessel["gross_tonnage"]) if vessel.get("gross_tonnage") else None,
        "route_types": list(vessel.get("route_types") or []),
        "flag_state": vessel.get("flag_state"),
        "subchapter": vessel.get("subchapter"),
        "manning_requirement": vessel.get("manning_requirement"),
        "route_limitations": vessel.get("route_limitations"),
        "inspection_certificate_type": vessel.get("inspection_certificate_type"),
        "official_number": additional.get("official_number"),
        "imo_number": additional.get("imo_number"),
        "call_sign": additional.get("call_sign"),
        "hull_material": additional.get("hull_material"),
        "expiration_date": additional.get("expiration_date"),
        "max_persons": additional.get("max_persons"),
        "lifesaving_equipment": additional.get("lifesaving_equipment"),
        "fire_equipment": additional.get("fire_equipment"),
    }


# ── PDF export ─────────────────────────────────────────────────────────────


def _generate_pdf(profile: dict, applicable_regs: list[dict]) -> bytes:
    """Generate a compliance summary PDF using fpdf2."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 12, "Vessel Compliance Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Generated {datetime.now(timezone.utc).strftime('%B %d, %Y at %H:%M UTC')}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, "RegKnot — Navigation aid only, not legal advice", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(8)

    # Vessel profile section
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, profile["name"], new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    fields = [
        ("Vessel Type", profile.get("vessel_type")),
        ("Gross Tonnage", profile.get("gross_tonnage")),
        ("Route Types", ", ".join(profile.get("route_types") or [])),
        ("Flag State", profile.get("flag_state")),
        ("Subchapter", profile.get("subchapter")),
        ("Official Number", profile.get("official_number")),
        ("IMO Number", profile.get("imo_number")),
        ("Call Sign", profile.get("call_sign")),
        ("Hull Material", profile.get("hull_material")),
        ("Manning Requirement", profile.get("manning_requirement")),
        ("Route Limitations", profile.get("route_limitations")),
        ("Certificate Type", profile.get("inspection_certificate_type")),
        ("Certificate Expiration", profile.get("expiration_date")),
        ("Max Persons", profile.get("max_persons")),
    ]

    for label, value in fields:
        if value:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(55, 7, f"{label}:", new_x="RIGHT")
            pdf.set_font("Helvetica", "", 10)
            pdf.cell(0, 7, str(value), new_x="LMARGIN", new_y="NEXT")

    # Equipment sections
    for label, key in [("Lifesaving Equipment", "lifesaving_equipment"), ("Fire Equipment", "fire_equipment")]:
        val = profile.get(key)
        if val:
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 8, label, new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 9)
            pdf.multi_cell(0, 5, str(val))

    # Applicable regulations
    if applicable_regs:
        pdf.ln(8)
        pdf.set_font("Helvetica", "B", 14)
        pdf.cell(0, 10, "Applicable Regulations", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

        for reg in applicable_regs:
            pdf.set_font("Helvetica", "B", 10)
            pdf.cell(0, 7, f"{reg['section_number']} - {reg['section_title']}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(80, 80, 80)
            pdf.cell(0, 5, f"Source: {reg['source']}", new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)

    return pdf.output()


@router.get("/vessel/{vessel_id}/pdf")
async def export_vessel_pdf(
    vessel_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> StreamingResponse:
    """Generate and download a compliance summary PDF for a vessel."""
    pool = await get_pool()
    vessel = await _load_vessel_profile(pool, vessel_id, _uuid.UUID(user.user_id))
    profile = _vessel_to_profile(vessel)

    # Get applicable regulations based on vessel characteristics
    route_types = vessel.get("route_types") or []
    subchapter = vessel.get("subchapter") or ""

    regs = await pool.fetch(
        """
        SELECT DISTINCT source, section_number, section_title
        FROM regulations
        WHERE (
            section_title ILIKE '%inspection%'
            OR section_title ILIKE '%certificate%'
            OR section_title ILIKE '%equipment%'
            OR section_title ILIKE '%safety%'
            OR section_title ILIKE '%manning%'
        )
        AND source IN ('cfr_33', 'cfr_46', 'solas', 'stcw', 'ism')
        ORDER BY source, section_number
        LIMIT 40
        """,
    )

    applicable_regs = [
        {"source": r["source"], "section_number": r["section_number"], "section_title": r["section_title"]}
        for r in regs
    ]

    pdf_bytes = _generate_pdf(profile, applicable_regs)

    safe_name = profile["name"].replace(" ", "_").replace("/", "-")
    filename = f"compliance_summary_{safe_name}.pdf"

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Share token ────────────────────────────────────────────────────────────


class ShareResponse(BaseModel):
    share_token: str
    share_url: str


@router.post("/vessel/{vessel_id}/share", response_model=ShareResponse)
async def create_share_token(
    vessel_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ShareResponse:
    """Generate or return existing share token for a vessel."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    vessel = await _load_vessel_profile(pool, vessel_id, user_id)

    if vessel.get("share_token"):
        return ShareResponse(
            share_token=vessel["share_token"],
            share_url=f"https://regknots.com/shared/{vessel['share_token']}",
        )

    token = secrets.token_urlsafe(16)
    await pool.execute(
        "UPDATE vessels SET share_token = $1 WHERE id = $2 AND user_id = $3",
        token, vessel_id, user_id,
    )

    return ShareResponse(
        share_token=token,
        share_url=f"https://regknots.com/shared/{token}",
    )


# ── Public shared profile ─────────────────────────────────────────────────


class SharedProfile(BaseModel):
    vessel_name: str
    vessel_type: str
    gross_tonnage: float | None
    route_types: list[str]
    flag_state: str | None
    subchapter: str | None
    manning_requirement: str | None
    route_limitations: str | None
    inspection_certificate_type: str | None
    official_number: str | None
    call_sign: str | None
    expiration_date: str | None
    max_persons: str | None


@router.get("/shared/{share_token}", response_model=SharedProfile)
async def get_shared_profile(share_token: str) -> SharedProfile:
    """Public endpoint — no auth required. Returns vessel compliance profile."""
    pool = await get_pool()
    vessel = await _load_vessel_by_token(pool, share_token)
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    profile = _vessel_to_profile(vessel)
    return SharedProfile(
        vessel_name=profile["name"],
        vessel_type=profile["vessel_type"],
        gross_tonnage=profile.get("gross_tonnage"),
        route_types=profile.get("route_types") or [],
        flag_state=profile.get("flag_state"),
        subchapter=profile.get("subchapter"),
        manning_requirement=profile.get("manning_requirement"),
        route_limitations=profile.get("route_limitations"),
        inspection_certificate_type=profile.get("inspection_certificate_type"),
        official_number=profile.get("official_number"),
        call_sign=profile.get("call_sign"),
        expiration_date=profile.get("expiration_date"),
        max_persons=profile.get("max_persons"),
    )

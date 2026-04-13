"""PSC inspection checklist generator.

POST /checklists/psc — generate a PSC inspection checklist for a vessel
"""

import json
import logging
import uuid as _uuid
from typing import Annotated

import asyncpg
from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checklists", tags=["checklists"])


class PSCRequest(BaseModel):
    vessel_id: str


class ChecklistItem(BaseModel):
    category: str
    item: str
    regulation: str
    notes: str | None = None


class PSCChecklist(BaseModel):
    vessel_name: str
    vessel_type: str
    checklist: list[ChecklistItem]
    generated_at: str


_PSC_SYSTEM_PROMPT = """\
You are a maritime compliance expert generating a Port State Control (PSC) \
inspection readiness checklist. Based on the vessel profile and applicable \
regulations provided, produce a structured JSON checklist.

Each item must reference the specific regulation (CFR section, SOLAS chapter, \
STCW code, etc.) that applies.

Categories should include (as applicable to the vessel):
- Safety Equipment & LSA
- Fire Safety
- Navigation & Communications
- Structural & Hull
- Pollution Prevention
- Manning & Certification
- ISM / SMS Documentation
- ISPS Security
- Working & Living Conditions

Return ONLY a JSON array of objects with these fields:
- category: the checklist category
- item: what to check/verify
- regulation: the specific regulation reference (e.g., "46 CFR 199.261", "SOLAS III/20")
- notes: optional brief guidance

Return ONLY the JSON array. No markdown, no explanation."""


@router.post("/psc", response_model=PSCChecklist)
async def generate_psc_checklist(
    body: PSCRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PSCChecklist:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel_id = _uuid.UUID(body.vessel_id)

    # Load vessel profile
    vessel = await pool.fetchrow(
        "SELECT * FROM vessels WHERE id = $1 AND user_id = $2",
        vessel_id, user_id,
    )
    if not vessel:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")

    # Build vessel context for the prompt
    additional = vessel["additional_details"] or {}
    if isinstance(additional, str):
        additional = json.loads(additional)

    vessel_context = f"""Vessel Profile:
- Name: {vessel['name']}
- Type: {vessel['vessel_type']}
- Gross Tonnage: {vessel['gross_tonnage'] or 'Unknown'}
- Route Types: {', '.join(vessel['route_types'] or [])}
- Flag State: {vessel['flag_state']}
- Subchapter: {vessel.get('subchapter') or 'Unknown'}
- Manning Requirement: {vessel.get('manning_requirement') or 'Unknown'}
- Route Limitations: {vessel.get('route_limitations') or 'None'}
- Inspection Certificate Type: {vessel.get('inspection_certificate_type') or 'Unknown'}"""

    if additional.get("lifesaving_equipment"):
        vessel_context += f"\n- Lifesaving Equipment: {additional['lifesaving_equipment']}"
    if additional.get("fire_equipment"):
        vessel_context += f"\n- Fire Equipment: {additional['fire_equipment']}"
    if additional.get("max_persons"):
        vessel_context += f"\n- Max Persons: {additional['max_persons']}"

    # Retrieve relevant regulations for context
    regs = await pool.fetch(
        """
        SELECT source, section_number, section_title, full_text
        FROM regulations
        WHERE source IN ('cfr_33', 'cfr_46', 'solas', 'stcw', 'ism')
          AND (
            full_text ILIKE '%inspection%'
            OR full_text ILIKE '%port state%'
            OR full_text ILIKE '%safety equipment%'
            OR section_title ILIKE '%inspection%'
            OR section_title ILIKE '%survey%'
          )
        ORDER BY source, section_number
        LIMIT 30
        """
    )

    reg_context = ""
    if regs:
        reg_context = "\n\nApplicable Regulations (excerpts):\n"
        for r in regs:
            text_preview = (r["full_text"] or "")[:300]
            reg_context += f"\n[{r['section_number']} — {r['section_title']}]\n{text_preview}\n"

    try:
        anthropic_client: AsyncAnthropic = request.app.state.anthropic
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=_PSC_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{vessel_context}{reg_context}\n\nGenerate a comprehensive PSC inspection readiness checklist for this vessel.",
            }],
        )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        items = json.loads(text.strip())

        from datetime import datetime, timezone
        checklist = [ChecklistItem(**item) for item in items]

        logger.info("PSC checklist generated: vessel=%s items=%d", vessel['name'], len(checklist))

        return PSCChecklist(
            vessel_name=vessel["name"],
            vessel_type=vessel["vessel_type"],
            checklist=checklist,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except json.JSONDecodeError:
        logger.exception("PSC checklist JSON parse failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate checklist. Please try again.",
        )
    except Exception:
        logger.exception("PSC checklist generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate checklist. Please try again.",
        )

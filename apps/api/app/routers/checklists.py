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
            max_tokens=8192,
            system=_PSC_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{vessel_context}{reg_context}\n\nGenerate a comprehensive PSC inspection readiness checklist for this vessel.",
            }],
        )

        if response.stop_reason == "max_tokens":
            logger.warning(
                "PSC checklist hit max_tokens — will attempt partial JSON recovery (vessel=%s)",
                vessel["name"],
            )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        items = _parse_or_recover_json(text)

        from datetime import datetime, timezone
        checklist = [ChecklistItem(**item) for item in items if _is_valid_item(item)]

        if not checklist:
            raise ValueError("No valid checklist items parsed")

        logger.info("PSC checklist generated: vessel=%s items=%d", vessel['name'], len(checklist))

        return PSCChecklist(
            vessel_name=vessel["name"],
            vessel_type=vessel["vessel_type"],
            checklist=checklist,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("PSC checklist generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate checklist. Please try again.",
        )


def _is_valid_item(item: dict) -> bool:
    """Check that a parsed item has the required fields."""
    return (
        isinstance(item, dict)
        and item.get("category")
        and item.get("item")
        and item.get("regulation")
    )


def _parse_or_recover_json(text: str) -> list[dict]:
    """Parse JSON array, recovering gracefully from truncation.

    Strategy:
    1. Try json.loads directly — works when response is complete.
    2. On failure, find the last complete object (closing "}") and
       truncate there, then close the array. This recovers truncated
       responses that hit max_tokens mid-string or mid-field.
    """
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        logger.warning("PSC: JSON parsed but not a list (type=%s)", type(parsed).__name__)
        return []
    except json.JSONDecodeError as exc:
        logger.warning("PSC: direct JSON parse failed (%s) — attempting recovery", str(exc)[:120])

    # Recovery: find the last complete object before the truncation point.
    # Walk backwards to find a "}," or "}" that's followed by whitespace/EOF.
    # Then close the array at that point.
    if not text.startswith("["):
        logger.error("PSC: response does not start with '[' — cannot recover")
        return []

    # Find last complete object by matching braces at depth 1 (inside the array)
    depth = 0
    last_complete_end = -1
    in_string = False
    escape_next = False

    for i, ch in enumerate(text):
        if escape_next:
            escape_next = False
            continue
        if ch == "\\":
            escape_next = True
            continue
        if ch == '"' and not escape_next:
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 1:  # We're back at array level — this object is complete
                last_complete_end = i

    if last_complete_end == -1:
        logger.error("PSC: no complete objects found in truncated response")
        return []

    recovered = text[: last_complete_end + 1] + "]"
    try:
        parsed = json.loads(recovered)
        logger.info("PSC: recovered %d items from truncated response", len(parsed))
        return parsed
    except json.JSONDecodeError:
        logger.exception("PSC: recovery attempt also failed to parse")
        return []

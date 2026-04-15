"""PSC inspection checklist generator with per-vessel persistence.

POST   /checklists/psc                      — generate + save (upserts on vessel)
GET    /checklists/psc/{vessel_id}          — load saved checklist if it exists
PATCH  /checklists/psc/{vessel_id}/checks   — update checked_indices
DELETE /checklists/psc/{vessel_id}          — discard saved checklist
"""

import json
import logging
import uuid as _uuid
from datetime import datetime, timezone
from typing import Annotated

from anthropic import AsyncAnthropic
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/checklists", tags=["checklists"])


# ── Models ─────────────────────────────────────────────────────────────────


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
    checked_indices: list[int] = []
    generated_at: str


class ChecksUpdate(BaseModel):
    checked_indices: list[int]


class ProfileIncompleteResponse(BaseModel):
    detail: str
    missing_fields: list[str]
    completeness_score: int
    required_score: int


# ── Prompt ─────────────────────────────────────────────────────────────────

_PSC_SYSTEM_PROMPT = """\
You are a maritime compliance expert generating a Port State Control (PSC) \
inspection readiness checklist. Based on the vessel profile and applicable \
regulations provided, produce a structured JSON array of checklist items.

STRICT OUTPUT RULES:
- Begin your response with `[` — no preamble, no explanation, no markdown.
- End with `]`.
- Maximum 7 categories total.
- Exactly 5 items per category (no fewer, no more).
- Each "item" text must be under 20 words and focused on a single check.
- Each "notes" field must be under 25 words and provide practical guidance.
- Each item must cite specific regulations (CFR section, SOLAS chapter, STCW \
code, ISM section). Multiple citations allowed, separated by semicolons.
- Prioritize items most likely to be flagged in an actual PSC inspection over \
comprehensive coverage.

Pick 7 categories from this list most applicable to the vessel:
- Safety Equipment & LSA
- Fire Safety
- Navigation & Communications
- Structural & Hull
- Pollution Prevention
- Manning & Certification
- ISM / SMS Documentation
- ISPS Security
- Working & Living Conditions

Each object must have exactly these fields:
- category: string
- item: string (under 20 words)
- regulation: string (specific citations)
- notes: string (under 25 words, practical guidance)

Return ONLY the JSON array."""


# ── Profile completeness gate ──────────────────────────────────────────────

_REQUIRED_COMPLETENESS_SCORE = 4  # Out of 6


def _score_vessel_profile(vessel: dict, additional: dict) -> tuple[int, list[str]]:
    """Score vessel profile completeness. Returns (score, missing_field_labels)."""
    score = 0
    missing: list[str] = []

    # 1. Vessel type (always required anyway, but count it)
    if vessel.get("vessel_type"):
        score += 1
    else:
        missing.append("Vessel type")

    # 2. Gross tonnage
    if vessel.get("gross_tonnage") is not None:
        score += 1
    else:
        missing.append("Gross tonnage")

    # 3. Route types
    if vessel.get("route_types") and len(vessel["route_types"]) > 0:
        score += 1
    else:
        missing.append("Route types")

    # 4. Subchapter
    if vessel.get("subchapter"):
        score += 1
    else:
        missing.append("USCG subchapter")

    # 5. Manning requirement OR inspection certificate type
    if vessel.get("manning_requirement") or vessel.get("inspection_certificate_type"):
        score += 1
    else:
        missing.append("Manning requirement or certificate type")

    # 6. Equipment details (from additional_details or COI extraction)
    if additional.get("lifesaving_equipment") or additional.get("fire_equipment") \
            or additional.get("max_persons") or additional.get("conditions_of_operation"):
        score += 1
    else:
        missing.append("Equipment or operational details")

    return score, missing


# ── Helpers ────────────────────────────────────────────────────────────────


async def _verify_vessel_ownership(
    pool, vessel_id: _uuid.UUID, user_id: _uuid.UUID,
) -> dict:
    """Load vessel row if owned by user. Raises 404 otherwise."""
    row = await pool.fetchrow(
        "SELECT * FROM vessels WHERE id = $1 AND user_id = $2",
        vessel_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")
    return dict(row)


def _is_valid_item(item: dict) -> bool:
    return (
        isinstance(item, dict)
        and bool(item.get("category"))
        and bool(item.get("item"))
        and bool(item.get("regulation"))
    )


def _parse_or_recover_json(text: str) -> list[dict]:
    """Parse a JSON array, recovering gracefully from truncation or prose preamble.

    1. Find the first `[` — slice from there (drops any preamble).
    2. Try json.loads directly.
    3. On failure, walk to find the last complete object and close the array.
    """
    start = text.find("[")
    if start == -1:
        logger.error("PSC: no '[' found in response")
        return []
    text = text[start:]

    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        return []
    except json.JSONDecodeError as exc:
        logger.warning("PSC: direct JSON parse failed (%s) — attempting recovery", str(exc)[:120])

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
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 1:
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


def _row_to_checklist(row: dict, vessel_name: str, vessel_type: str) -> PSCChecklist:
    items_raw = row["items"]
    if isinstance(items_raw, str):
        items_raw = json.loads(items_raw)
    checklist = [ChecklistItem(**item) for item in items_raw if _is_valid_item(item)]
    return PSCChecklist(
        vessel_name=vessel_name,
        vessel_type=vessel_type,
        checklist=checklist,
        checked_indices=list(row["checked_indices"] or []),
        generated_at=row["generated_at"].isoformat(),
    )


# ── Endpoints ──────────────────────────────────────────────────────────────


@router.post("/psc", response_model=PSCChecklist)
async def generate_psc_checklist(
    body: PSCRequest,
    request: Request,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PSCChecklist:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel_id = _uuid.UUID(body.vessel_id)

    vessel = await _verify_vessel_ownership(pool, vessel_id, user_id)

    additional = vessel.get("additional_details") or {}
    if isinstance(additional, str):
        additional = json.loads(additional)

    # ── Completeness gate ────────────────────────────────────────────────
    score, missing = _score_vessel_profile(vessel, additional)
    if score < _REQUIRED_COMPLETENESS_SCORE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": (
                    f"Vessel profile is too sparse to generate an accurate PSC checklist "
                    f"({score}/{6} fields populated, {_REQUIRED_COMPLETENESS_SCORE} required). "
                    f"Please add missing details to the vessel profile."
                ),
                "missing_fields": missing,
                "completeness_score": score,
                "required_score": _REQUIRED_COMPLETENESS_SCORE,
            },
        )

    # ── Build context ────────────────────────────────────────────────────
    vessel_context = f"""Vessel Profile:
- Name: {vessel['name']}
- Type: {vessel['vessel_type']}
- Gross Tonnage: {vessel.get('gross_tonnage') or 'Unknown'}
- Route Types: {', '.join(vessel.get('route_types') or [])}
- Flag State: {vessel.get('flag_state')}
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
    if additional.get("conditions_of_operation"):
        vessel_context += f"\n- Conditions of Operation: {additional['conditions_of_operation']}"

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

    # ── Generate ─────────────────────────────────────────────────────────
    try:
        anthropic_client: AsyncAnthropic = request.app.state.anthropic
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=_PSC_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{vessel_context}{reg_context}\n\nGenerate a focused PSC inspection readiness checklist for this vessel. Remember: exactly 5 items per category, 7 categories max, concise item and notes text.",
            }],
        )

        if response.stop_reason == "max_tokens":
            logger.warning(
                "PSC checklist hit max_tokens — will attempt recovery (vessel=%s)",
                vessel["name"],
            )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        items = _parse_or_recover_json(text)
        valid_items = [item for item in items if _is_valid_item(item)]

        if not valid_items:
            raise ValueError("No valid checklist items parsed")

        logger.info(
            "PSC checklist generated: vessel=%s items=%d (score=%d/6)",
            vessel["name"], len(valid_items), score,
        )

        # ── Save / upsert ───────────────────────────────────────────────
        items_json = json.dumps(valid_items)
        now = datetime.now(timezone.utc)
        await pool.execute(
            """
            INSERT INTO psc_checklists (user_id, vessel_id, items, checked_indices, generated_at)
            VALUES ($1, $2, $3::jsonb, '{}', $4)
            ON CONFLICT (user_id, vessel_id) DO UPDATE
                SET items = EXCLUDED.items,
                    checked_indices = '{}',
                    generated_at = EXCLUDED.generated_at
            """,
            user_id, vessel_id, items_json, now,
        )

        checklist = [ChecklistItem(**item) for item in valid_items]
        return PSCChecklist(
            vessel_name=vessel["name"],
            vessel_type=vessel["vessel_type"],
            checklist=checklist,
            checked_indices=[],
            generated_at=now.isoformat(),
        )

    except HTTPException:
        raise
    except Exception:
        logger.exception("PSC checklist generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate checklist. Please try again.",
        )


@router.get("/psc/{vessel_id}", response_model=PSCChecklist | None)
async def get_saved_psc_checklist(
    vessel_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PSCChecklist | None:
    """Load the saved PSC checklist for this vessel, if any."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    vessel = await _verify_vessel_ownership(pool, vessel_id, user_id)

    row = await pool.fetchrow(
        """
        SELECT items, checked_indices, generated_at
        FROM psc_checklists
        WHERE user_id = $1 AND vessel_id = $2
        """,
        user_id, vessel_id,
    )
    if not row:
        return None

    return _row_to_checklist(dict(row), vessel["name"], vessel["vessel_type"])


@router.patch("/psc/{vessel_id}/checks", status_code=status.HTTP_204_NO_CONTENT)
async def update_checks(
    vessel_id: _uuid.UUID,
    body: ChecksUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Update which items are checked off."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)

    # Verify ownership via psc_checklists (will fail silently if missing)
    result = await pool.execute(
        """
        UPDATE psc_checklists
        SET checked_indices = $1::integer[]
        WHERE user_id = $2 AND vessel_id = $3
        """,
        list(set(body.checked_indices)),  # dedupe
        user_id, vessel_id,
    )
    if result == "UPDATE 0":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No saved checklist for this vessel",
        )


@router.delete("/psc/{vessel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_saved_checklist(
    vessel_id: _uuid.UUID,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Discard a saved checklist."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    result = await pool.execute(
        "DELETE FROM psc_checklists WHERE user_id = $1 AND vessel_id = $2",
        user_id, vessel_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No saved checklist")

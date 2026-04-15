"""PSC inspection checklist generator with persistence and item-level editing.

POST   /checklists/psc                            — generate + save (upserts)
GET    /checklists/psc/{vessel_id}                — load saved checklist
DELETE /checklists/psc/{vessel_id}                — discard saved
PATCH  /checklists/psc/{vessel_id}/checks         — update checked_indices
PATCH  /checklists/psc/{vessel_id}/items/{index}  — edit item at index
DELETE /checklists/psc/{vessel_id}/items/{index}  — delete item at index
POST   /checklists/psc/{vessel_id}/items          — add custom item
"""

import json
import logging
import uuid as _uuid
from datetime import datetime, timezone
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


# ── Models ─────────────────────────────────────────────────────────────────


class PSCRequest(BaseModel):
    vessel_id: str


class ChecklistItem(BaseModel):
    category: str
    item: str
    regulation: str
    notes: str | None = None
    user_added: bool = False


class OmittedCategory(BaseModel):
    category: str
    reason: str


class CoverageInfo(BaseModel):
    included_categories: list[str]
    omitted_categories: list[OmittedCategory]


class PSCChecklist(BaseModel):
    vessel_name: str
    vessel_type: str
    checklist: list[ChecklistItem]
    checked_indices: list[int] = []
    coverage: CoverageInfo | None = None
    generated_at: str


class ChecksUpdate(BaseModel):
    checked_indices: list[int]


class ItemUpdate(BaseModel):
    item: str | None = None
    regulation: str | None = None
    notes: str | None = None


class ItemAdd(BaseModel):
    category: str
    item: str
    regulation: str
    notes: str | None = None


# ── Prompt ─────────────────────────────────────────────────────────────────

_PSC_SYSTEM_PROMPT = """\
You are a maritime compliance expert generating a Port State Control (PSC) \
inspection readiness checklist. Based on the vessel profile and applicable \
regulations provided, produce a structured JSON OBJECT.

STRICT OUTPUT RULES:
- Begin your response with `{` — no preamble, no explanation, no markdown.
- End with `}`.
- Do NOT create two items that cover essentially the same check, even across \
different categories. Before finalizing, review your items and merge or drop \
any redundant entries.
- Maximum 8 categories total, exactly 5 items per category.
- Each "item" text must be under 20 words, focused on a single check.
- Each "notes" field must be under 25 words, with practical guidance.
- Each item must cite specific regulations (CFR section, SOLAS chapter, STCW \
code, ISM section). Multiple citations allowed, separated by semicolons.
- Prioritize items most likely to be flagged in an actual PSC inspection.

MANDATORY CATEGORIES (always include these two):
- Safety Equipment & LSA
- Structural & Hull

ADDITIONAL CATEGORIES — pick 4-6 more that apply to this vessel:
- Fire Safety
- Navigation & Communications
- Pollution Prevention
- Manning & Certification
- ISM / SMS Documentation
- ISPS Security
- Working & Living Conditions

For Structural & Hull, always include items covering: hull integrity \
inspection, watertight penetrations/closures, bilge pump system, and any \
vessel-specific structural concerns (e.g., DUKW stern reference line, hull \
plating for steel vessels, sea cocks).

OUTPUT SHAPE — return exactly this JSON object structure:
{
  "items": [
    {"category": string, "item": string, "regulation": string, "notes": string},
    ...
  ],
  "coverage": {
    "included_categories": [list of categories you included],
    "omitted_categories": [
      {"category": string, "reason": "brief why this does not apply (under 20 words)"}
    ]
  }
}

For omitted_categories, briefly explain why a category in the ADDITIONAL \
list was not applicable to this specific vessel (e.g., "Vessel is domestic \
inland — not subject to 33 CFR Part 104 ISPS requirements"). Do NOT include \
categories that simply didn't fit in the 8-category budget without a real \
applicability reason. If no categories were excluded for applicability, \
return an empty array.

Return ONLY the JSON object."""


# ── Profile completeness gate ──────────────────────────────────────────────

_REQUIRED_COMPLETENESS_SCORE = 4


def _score_vessel_profile(vessel: dict, additional: dict) -> tuple[int, list[str]]:
    score = 0
    missing: list[str] = []

    if vessel.get("vessel_type"):
        score += 1
    else:
        missing.append("Vessel type")

    if vessel.get("gross_tonnage") is not None:
        score += 1
    else:
        missing.append("Gross tonnage")

    if vessel.get("route_types") and len(vessel["route_types"]) > 0:
        score += 1
    else:
        missing.append("Route types")

    if vessel.get("subchapter"):
        score += 1
    else:
        missing.append("USCG subchapter")

    if vessel.get("manning_requirement") or vessel.get("inspection_certificate_type"):
        score += 1
    else:
        missing.append("Manning requirement or certificate type")

    if additional.get("lifesaving_equipment") or additional.get("fire_equipment") \
            or additional.get("max_persons") or additional.get("conditions_of_operation"):
        score += 1
    else:
        missing.append("Equipment or operational details")

    return score, missing


# ── Helpers ────────────────────────────────────────────────────────────────


async def _verify_vessel_ownership(
    pool: asyncpg.Pool, vessel_id: _uuid.UUID, user_id: _uuid.UUID,
) -> dict:
    row = await pool.fetchrow(
        "SELECT * FROM vessels WHERE id = $1 AND user_id = $2",
        vessel_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vessel not found")
    return dict(row)


async def _load_checklist_row(
    pool: asyncpg.Pool, user_id: _uuid.UUID, vessel_id: _uuid.UUID,
) -> dict | None:
    row = await pool.fetchrow(
        "SELECT * FROM psc_checklists WHERE user_id = $1 AND vessel_id = $2",
        user_id, vessel_id,
    )
    return dict(row) if row else None


def _is_valid_item(item: dict) -> bool:
    return (
        isinstance(item, dict)
        and bool(item.get("category"))
        and bool(item.get("item"))
        and bool(item.get("regulation"))
    )


def _parse_or_recover_json(text: str) -> dict | list:
    """Parse the AI response, recovering gracefully from truncation or prose preamble.

    Expected shape: {"items": [...], "coverage": {...}}
    Legacy shape: just an array [...]
    """
    # Strip any preamble before the first JSON structural character.
    first_brace = text.find("{")
    first_bracket = text.find("[")
    starts = [s for s in (first_brace, first_bracket) if s != -1]
    if not starts:
        logger.error("PSC: no JSON structure found in response")
        return {}
    start = min(starts)
    text = text[start:]

    try:
        parsed = json.loads(text)
        return parsed
    except json.JSONDecodeError as exc:
        logger.warning("PSC: direct JSON parse failed (%s) — attempting recovery", str(exc)[:120])

    # Recovery: find the last complete top-level item and close structure.
    depth = 0
    last_complete_end = -1
    in_string = False
    escape_next = False

    # Are we parsing an object (first char `{`) or array (`[`)?
    is_object = text.startswith("{")

    # For object shape, we recover the `items` array specifically; find its `[`
    if is_object:
        items_start = text.find('"items"')
        if items_start == -1:
            logger.error("PSC: truncated response has no 'items' field")
            return {}
        arr_start = text.find("[", items_start)
        if arr_start == -1:
            return {}
        walk_from = arr_start
    else:
        walk_from = 0

    for i in range(walk_from, len(text)):
        ch = text[i]
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
            if depth == 1 if is_object else depth == 0:
                last_complete_end = i

    if last_complete_end == -1:
        logger.error("PSC: no complete objects found in truncated response")
        return {}

    if is_object:
        # Build a minimal valid object using just the recovered items.
        recovered = text[walk_from: last_complete_end + 1] + "]"
        try:
            items = json.loads(recovered)
            logger.info("PSC: recovered %d items from truncated object response", len(items))
            return {"items": items, "coverage": {"included_categories": [], "omitted_categories": []}}
        except json.JSONDecodeError:
            logger.exception("PSC: recovery of object form failed")
            return {}
    else:
        recovered = text[: last_complete_end + 1] + "]"
        try:
            items = json.loads(recovered)
            logger.info("PSC: recovered %d items from truncated array response", len(items))
            return items
        except json.JSONDecodeError:
            logger.exception("PSC: recovery of array form failed")
            return []


def _extract_items_and_coverage(parsed) -> tuple[list[dict], dict | None]:
    """Normalize parser output into (items, coverage). Coverage may be None."""
    if isinstance(parsed, list):
        return [x for x in parsed if _is_valid_item(x)], None
    if isinstance(parsed, dict):
        raw_items = parsed.get("items") or []
        items = [x for x in raw_items if _is_valid_item(x)]
        coverage = parsed.get("coverage")
        if coverage and isinstance(coverage, dict):
            return items, coverage
        return items, None
    return [], None


def _row_to_checklist(row: dict, vessel_name: str, vessel_type: str) -> PSCChecklist:
    items_raw = row["items"]
    if isinstance(items_raw, str):
        items_raw = json.loads(items_raw)
    checklist = [ChecklistItem(**item) for item in items_raw if _is_valid_item(item)]

    coverage: CoverageInfo | None = None
    cov_raw = row.get("coverage")
    if cov_raw:
        if isinstance(cov_raw, str):
            cov_raw = json.loads(cov_raw)
        try:
            omitted = [OmittedCategory(**c) for c in cov_raw.get("omitted_categories", []) if isinstance(c, dict)]
            coverage = CoverageInfo(
                included_categories=list(cov_raw.get("included_categories") or []),
                omitted_categories=omitted,
            )
        except Exception:
            coverage = None

    return PSCChecklist(
        vessel_name=vessel_name,
        vessel_type=vessel_type,
        checklist=checklist,
        checked_indices=list(row["checked_indices"] or []),
        coverage=coverage,
        generated_at=row["generated_at"].isoformat(),
    )


async def _log_feedback(
    pool: asyncpg.Pool,
    user_id: _uuid.UUID,
    vessel_id: _uuid.UUID,
    checklist_id: _uuid.UUID,
    action_type: str,
    original_item: dict | None,
    final_item: dict | None,
    item_index: int | None,
) -> None:
    """Silently record a user action. Never raises — logging failure must not block UX."""
    try:
        await pool.execute(
            """
            INSERT INTO checklist_feedback
                (user_id, vessel_id, checklist_id, action_type, original_item, final_item, item_index)
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7)
            """,
            user_id, vessel_id, checklist_id, action_type,
            json.dumps(original_item) if original_item else None,
            json.dumps(final_item) if final_item else None,
            item_index,
        )
    except Exception:
        logger.exception("Failed to log checklist feedback (user=%s, action=%s)", user_id, action_type)


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

    score, missing = _score_vessel_profile(vessel, additional)
    if score < _REQUIRED_COMPLETENESS_SCORE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "detail": (
                    f"Vessel profile is too sparse to generate an accurate PSC checklist "
                    f"({score}/6 fields populated, {_REQUIRED_COMPLETENESS_SCORE} required). "
                    f"Please add missing details to the vessel profile."
                ),
                "missing_fields": missing,
                "completeness_score": score,
                "required_score": _REQUIRED_COMPLETENESS_SCORE,
            },
        )

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

    try:
        anthropic_client: AsyncAnthropic = request.app.state.anthropic
        response = await anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=_PSC_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"{vessel_context}{reg_context}\n\nGenerate a focused PSC inspection readiness checklist for this vessel. Exactly 5 items per category, 8 categories max, concise item and notes text. Include the coverage object explaining any applicable categories omitted.",
            }],
        )

        if response.stop_reason == "max_tokens":
            logger.warning(
                "PSC checklist hit max_tokens (vessel=%s) — attempting recovery",
                vessel["name"],
            )

        text = response.content[0].text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        parsed = _parse_or_recover_json(text)
        items, coverage_dict = _extract_items_and_coverage(parsed)

        if not items:
            raise ValueError("No valid checklist items parsed")

        # Mark user_added=false on all AI-generated items
        for item in items:
            item["user_added"] = False

        logger.info(
            "PSC checklist generated: vessel=%s items=%d score=%d/6",
            vessel["name"], len(items), score,
        )

        now = datetime.now(timezone.utc)
        checklist_row = await pool.fetchrow(
            """
            INSERT INTO psc_checklists
                (user_id, vessel_id, items, checked_indices, coverage, generated_at)
            VALUES ($1, $2, $3::jsonb, '{}', $4::jsonb, $5)
            ON CONFLICT (user_id, vessel_id) DO UPDATE
                SET items = EXCLUDED.items,
                    checked_indices = '{}',
                    coverage = EXCLUDED.coverage,
                    generated_at = EXCLUDED.generated_at
            RETURNING id
            """,
            user_id, vessel_id,
            json.dumps(items),
            json.dumps(coverage_dict) if coverage_dict else None,
            now,
        )

        return _row_to_checklist(
            {
                "items": items,
                "checked_indices": [],
                "coverage": coverage_dict,
                "generated_at": now,
            },
            vessel["name"], vessel["vessel_type"],
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
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel = await _verify_vessel_ownership(pool, vessel_id, user_id)

    row = await _load_checklist_row(pool, user_id, vessel_id)
    if not row:
        return None
    return _row_to_checklist(row, vessel["name"], vessel["vessel_type"])


@router.patch("/psc/{vessel_id}/checks", status_code=status.HTTP_204_NO_CONTENT)
async def update_checks(
    vessel_id: _uuid.UUID,
    body: ChecksUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    result = await pool.execute(
        """
        UPDATE psc_checklists
        SET checked_indices = $1::integer[]
        WHERE user_id = $2 AND vessel_id = $3
        """,
        list(set(body.checked_indices)),
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
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    result = await pool.execute(
        "DELETE FROM psc_checklists WHERE user_id = $1 AND vessel_id = $2",
        user_id, vessel_id,
    )
    if result == "DELETE 0":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No saved checklist")


@router.patch("/psc/{vessel_id}/items/{index}", response_model=PSCChecklist)
async def edit_item(
    vessel_id: _uuid.UUID,
    index: int,
    body: ItemUpdate,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PSCChecklist:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel = await _verify_vessel_ownership(pool, vessel_id, user_id)

    row = await _load_checklist_row(pool, user_id, vessel_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No saved checklist")

    items = row["items"]
    if isinstance(items, str):
        items = json.loads(items)
    items = list(items)

    if index < 0 or index >= len(items):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item index out of range")

    original = dict(items[index])
    updates = body.model_dump(exclude_unset=True)
    for key in ("item", "regulation", "notes"):
        if key in updates and updates[key] is not None:
            items[index][key] = updates[key]

    await pool.execute(
        "UPDATE psc_checklists SET items = $1::jsonb WHERE user_id = $2 AND vessel_id = $3",
        json.dumps(items), user_id, vessel_id,
    )

    await _log_feedback(
        pool, user_id, vessel_id, row["id"], "edit",
        original_item=original,
        final_item=items[index],
        item_index=index,
    )

    updated = await _load_checklist_row(pool, user_id, vessel_id)
    return _row_to_checklist(updated, vessel["name"], vessel["vessel_type"])


@router.delete("/psc/{vessel_id}/items/{index}", response_model=PSCChecklist)
async def delete_item(
    vessel_id: _uuid.UUID,
    index: int,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PSCChecklist:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel = await _verify_vessel_ownership(pool, vessel_id, user_id)

    row = await _load_checklist_row(pool, user_id, vessel_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No saved checklist")

    items = row["items"]
    if isinstance(items, str):
        items = json.loads(items)
    items = list(items)

    if index < 0 or index >= len(items):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Item index out of range")

    original = dict(items[index])
    del items[index]

    # Remap checked_indices: remove index, shift down higher indices by 1.
    old_checks = list(row["checked_indices"] or [])
    new_checks: list[int] = []
    for c in old_checks:
        if c == index:
            continue
        if c > index:
            new_checks.append(c - 1)
        else:
            new_checks.append(c)

    await pool.execute(
        """
        UPDATE psc_checklists
        SET items = $1::jsonb, checked_indices = $2::integer[]
        WHERE user_id = $3 AND vessel_id = $4
        """,
        json.dumps(items), new_checks, user_id, vessel_id,
    )

    await _log_feedback(
        pool, user_id, vessel_id, row["id"], "delete",
        original_item=original,
        final_item=None,
        item_index=index,
    )

    updated = await _load_checklist_row(pool, user_id, vessel_id)
    return _row_to_checklist(updated, vessel["name"], vessel["vessel_type"])


@router.post("/psc/{vessel_id}/items", response_model=PSCChecklist, status_code=status.HTTP_201_CREATED)
async def add_item(
    vessel_id: _uuid.UUID,
    body: ItemAdd,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PSCChecklist:
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    vessel = await _verify_vessel_ownership(pool, vessel_id, user_id)

    row = await _load_checklist_row(pool, user_id, vessel_id)
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No saved checklist")

    if not body.category.strip() or not body.item.strip() or not body.regulation.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Category, item, and regulation are required",
        )

    items = row["items"]
    if isinstance(items, str):
        items = json.loads(items)
    items = list(items)

    new_item = {
        "category": body.category.strip(),
        "item": body.item.strip(),
        "regulation": body.regulation.strip(),
        "notes": (body.notes or "").strip() or None,
        "user_added": True,
    }
    items.append(new_item)

    await pool.execute(
        "UPDATE psc_checklists SET items = $1::jsonb WHERE user_id = $2 AND vessel_id = $3",
        json.dumps(items), user_id, vessel_id,
    )

    await _log_feedback(
        pool, user_id, vessel_id, row["id"], "add",
        original_item=None,
        final_item=new_item,
        item_index=len(items) - 1,
    )

    updated = await _load_checklist_row(pool, user_id, vessel_id)
    return _row_to_checklist(updated, vessel["name"], vessel["vessel_type"])

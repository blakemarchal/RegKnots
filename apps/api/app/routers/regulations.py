"""
GET /regulations/{source}/{section_number} — fetch full text for a regulation section.

section_number is URL-encoded by the client (e.g. "133.45" → "133.45", "164.01-5" → "164.01-5").
If a section has multiple chunks they are concatenated in chunk_index order.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status
from pydantic import BaseModel
from typing import Annotated

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/regulations", tags=["regulations"])


class RegulationDetail(BaseModel):
    source: str
    section_number: str
    section_title: str | None
    full_text: str
    effective_date: str | None
    up_to_date_as_of: str | None


@router.get("/{source}/{section_number}", response_model=RegulationDetail)
async def get_regulation(
    source: Annotated[str, Path(description="Regulation source, e.g. cfr_46")],
    section_number: Annotated[str, Path(description="CFR section number, e.g. 133.45")],
    _user: Annotated[CurrentUser, Depends(get_current_user)],
    pool=Depends(get_pool),
) -> RegulationDetail:
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT section_title, full_text, effective_date, up_to_date_as_of
            FROM regulations
            WHERE source = $1 AND section_number = $2
            ORDER BY chunk_index
            """,
            source,
            section_number,
        )

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Regulation {source}/{section_number} not found",
        )

    section_title = rows[0]["section_title"]
    full_text = "\n\n".join(r["full_text"] for r in rows if r["full_text"])
    effective_date = rows[0]["effective_date"]
    up_to_date_as_of = rows[0]["up_to_date_as_of"]

    return RegulationDetail(
        source=source,
        section_number=section_number,
        section_title=section_title,
        full_text=full_text,
        effective_date=str(effective_date) if effective_date else None,
        up_to_date_as_of=str(up_to_date_as_of) if up_to_date_as_of else None,
    )

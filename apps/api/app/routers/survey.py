"""Pilot survey endpoints — submit and retrieve feedback responses."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool
from app.routers.admin import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/survey", tags=["survey"])


# ── Submit survey ────────────────────────────────────────────────────────────

class PilotSurveyRequest(BaseModel):
    overall_rating: int = Field(ge=1, le=5)
    usefulness: str | None = None
    favorite_feature: str | None = None
    missing_feature: str | None = None
    would_subscribe: bool | None = None
    price_feedback: str | None = None
    vessel_type_used: str | None = None
    additional_comments: str | None = None


class PilotSurveyResult(BaseModel):
    saved: bool


@router.post("/pilot", response_model=PilotSurveyResult)
async def submit_pilot_survey(
    body: PilotSurveyRequest,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PilotSurveyResult:
    """Submit a pilot survey response. Prevents duplicate submissions."""
    pool = await get_pool()
    user_uuid = uuid.UUID(current_user.user_id)

    # Check for existing submission
    existing = await pool.fetchval(
        "SELECT 1 FROM pilot_survey_responses WHERE user_id = $1 LIMIT 1",
        user_uuid,
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already submitted feedback. Thank you!",
        )

    await pool.execute(
        """
        INSERT INTO pilot_survey_responses
            (user_id, overall_rating, usefulness, favorite_feature,
             missing_feature, would_subscribe, price_feedback,
             vessel_type_used, additional_comments)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        """,
        user_uuid,
        body.overall_rating,
        body.usefulness,
        body.favorite_feature,
        body.missing_feature,
        body.would_subscribe,
        body.price_feedback,
        body.vessel_type_used,
        body.additional_comments,
    )

    logger.info("Pilot survey submitted by user %s (rating=%d)", current_user.email, body.overall_rating)
    return PilotSurveyResult(saved=True)


# ── Check if user already submitted ─────────────────────────────────────────

class SurveyStatusResult(BaseModel):
    submitted: bool


@router.get("/pilot/status", response_model=SurveyStatusResult)
async def survey_status(
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> SurveyStatusResult:
    """Check if current user has already submitted a pilot survey."""
    pool = await get_pool()
    existing = await pool.fetchval(
        "SELECT 1 FROM pilot_survey_responses WHERE user_id = $1 LIMIT 1",
        uuid.UUID(current_user.user_id),
    )
    return SurveyStatusResult(submitted=bool(existing))


# ── Admin: list responses ────────────────────────────────────────────────────

class SurveyResponseAdmin(BaseModel):
    id: str
    email: str
    full_name: str | None
    overall_rating: int
    usefulness: str | None
    favorite_feature: str | None
    missing_feature: str | None
    would_subscribe: bool | None
    price_feedback: str | None
    vessel_type_used: str | None
    additional_comments: str | None
    created_at: str


class SurveyAggregates(BaseModel):
    total_responses: int
    average_rating: float
    would_subscribe_pct: float
    top_missing_feature: str | None
    responses: list[SurveyResponseAdmin]


@router.get("/admin/responses", response_model=SurveyAggregates)
async def admin_survey_responses(
    _admin: Annotated[CurrentUser, Depends(require_admin)],
) -> SurveyAggregates:
    """Return all survey responses with aggregates for the admin dashboard."""
    pool = await get_pool()

    rows = await pool.fetch(
        """
        SELECT s.id, u.email, u.full_name,
               s.overall_rating, s.usefulness, s.favorite_feature,
               s.missing_feature, s.would_subscribe, s.price_feedback,
               s.vessel_type_used, s.additional_comments, s.created_at
        FROM pilot_survey_responses s
        JOIN users u ON u.id = s.user_id
        ORDER BY s.created_at DESC
        """
    )

    responses = [
        SurveyResponseAdmin(
            id=str(r["id"]),
            email=r["email"],
            full_name=r["full_name"],
            overall_rating=r["overall_rating"],
            usefulness=r["usefulness"],
            favorite_feature=r["favorite_feature"],
            missing_feature=r["missing_feature"],
            would_subscribe=r["would_subscribe"],
            price_feedback=r["price_feedback"],
            vessel_type_used=r["vessel_type_used"],
            additional_comments=r["additional_comments"],
            created_at=r["created_at"].isoformat() if r["created_at"] else "",
        )
        for r in rows
    ]

    total = len(responses)
    avg_rating = sum(r.overall_rating for r in responses) / total if total else 0.0
    yes_count = sum(1 for r in responses if r.would_subscribe is True)
    sub_pct = (yes_count / total * 100) if total else 0.0

    # Most requested missing feature
    feature_counts: dict[str, int] = {}
    for r in responses:
        if r.missing_feature:
            feature_counts[r.missing_feature] = feature_counts.get(r.missing_feature, 0) + 1
    top_feature = max(feature_counts, key=feature_counts.get) if feature_counts else None  # type: ignore[arg-type]

    return SurveyAggregates(
        total_responses=total,
        average_rating=round(avg_rating, 1),
        would_subscribe_pct=round(sub_pct, 0),
        top_missing_feature=top_feature,
        responses=responses,
    )

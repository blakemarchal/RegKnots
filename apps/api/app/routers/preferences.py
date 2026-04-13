"""Notification preference endpoints.

GET  /preferences/notifications  — get current preferences
PUT  /preferences/notifications  — update preferences
"""

import json
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/preferences", tags=["preferences"])


class NotificationPreferences(BaseModel):
    cert_expiry_reminders: bool = True
    cert_expiry_days: list[int] = Field(default=[90, 30, 7])
    reg_change_digest: bool = True
    reg_digest_frequency: str = Field(default="weekly", pattern="^(weekly|biweekly)$")


@router.get("/notifications", response_model=NotificationPreferences)
async def get_notification_preferences(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> NotificationPreferences:
    pool = await get_pool()
    row = await pool.fetchval(
        "SELECT notification_preferences FROM users WHERE id = $1",
        uuid.UUID(user.user_id),
    )
    if row is None:
        return NotificationPreferences()
    data = json.loads(row) if isinstance(row, str) else row
    return NotificationPreferences(**data)


@router.put("/notifications", response_model=NotificationPreferences)
async def update_notification_preferences(
    body: NotificationPreferences,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> NotificationPreferences:
    pool = await get_pool()
    # Only allow valid expiry day values
    valid_days = [d for d in body.cert_expiry_days if d in (90, 30, 7)]
    body.cert_expiry_days = valid_days or [90, 30, 7]

    await pool.execute(
        "UPDATE users SET notification_preferences = $1 WHERE id = $2",
        json.dumps(body.model_dump()),
        uuid.UUID(user.user_id),
    )
    return body

"""Notification endpoints for in-app banners."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: str
    title: str
    body: str
    notification_type: str
    source: str | None
    link_url: str | None
    created_at: str


@router.get("/active", response_model=list[NotificationOut])
async def get_active_notifications(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[NotificationOut]:
    pool = await get_pool()
    rows = await pool.fetch(
        """
        SELECT n.id, n.title, n.body, n.notification_type, n.source, n.link_url, n.created_at
        FROM notifications n
        WHERE n.is_active = true
          AND n.id NOT IN (
            SELECT notification_id FROM user_notification_dismissals WHERE user_id = $1
          )
        ORDER BY n.created_at DESC
        LIMIT 5
        """,
        uuid.UUID(user.user_id),
    )
    return [
        NotificationOut(
            id=str(r["id"]),
            title=r["title"],
            body=r["body"],
            notification_type=r["notification_type"],
            source=r["source"],
            link_url=r["link_url"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.post("/{notification_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_notification(
    notification_id: str,
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    pool = await get_pool()
    await pool.execute(
        """
        INSERT INTO user_notification_dismissals (user_id, notification_id)
        VALUES ($1, $2)
        ON CONFLICT DO NOTHING
        """,
        uuid.UUID(user.user_id),
        uuid.UUID(notification_id),
    )

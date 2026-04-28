"""Notification endpoints for in-app banners.

Sprint D6.21 — flag-silo: filter notifications by the user's vessel
flag jurisdiction. A US-flag user shouldn't see UK MCA updates, and
a UK-flag user shouldn't see US CFR updates. Generic notifications
(no `source`) and international-instrument updates (SOLAS, COLREGs,
STCW, ISM, MARPOL, IMDG) always show. When the user has no flag
information anywhere, all notifications show — better to over-show
on a fresh account than to suppress signal silently.
"""

import logging
import sys
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

# rag package is sibling of apps/api and not on the default sys.path —
# add it once so we can pull the canonical source→jurisdiction map.
_RAG_PATH = "/opt/RegKnots/packages/rag"
if _RAG_PATH not in sys.path:
    sys.path.insert(0, _RAG_PATH)
try:
    from rag.jurisdiction import flag_to_jurisdiction, jurisdictions_for_source
except ImportError:  # pragma: no cover — local dev path resolution
    flag_to_jurisdiction = None
    jurisdictions_for_source = None

logger = logging.getLogger(__name__)

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

    # ── Derive the user's allow-set of jurisdiction codes from their
    # vessel flag(s). Empty set = no flag anywhere → no filter applied.
    user_juris: set[str] = set()
    if flag_to_jurisdiction is not None:
        flag_rows = await pool.fetch(
            "SELECT DISTINCT flag_state FROM vessels "
            "WHERE user_id = $1 AND flag_state IS NOT NULL AND flag_state <> ''",
            uuid.UUID(user.user_id),
        )
        for row in flag_rows:
            code = flag_to_jurisdiction(row["flag_state"])
            if code:
                user_juris.add(code)

    rows = await pool.fetch(
        """
        SELECT n.id, n.title, n.body, n.notification_type, n.source, n.link_url, n.created_at
        FROM notifications n
        WHERE n.is_active = true
          AND n.id NOT IN (
            SELECT notification_id FROM user_notification_dismissals WHERE user_id = $1
          )
        ORDER BY n.created_at DESC
        LIMIT 50
        """,
        uuid.UUID(user.user_id),
    )

    # ── Apply jurisdictional filter when the user has any flag signal.
    # Notifications with no `source` are always shown (system-wide
    # announcements). Notifications whose source maps to 'intl' tags
    # are always shown (universal instruments). National-flag-only
    # tags are shown only if they intersect the user's jurisdictions.
    filtered = []
    for r in rows:
        src = r["source"]
        if not src:
            filtered.append(r)
            continue
        if not user_juris or jurisdictions_for_source is None:
            # No flag info OR rag module unavailable → no filter.
            filtered.append(r)
            continue
        notif_juris = jurisdictions_for_source(src)
        if "intl" in notif_juris:
            filtered.append(r)
            continue
        if any(j in user_juris for j in notif_juris):
            filtered.append(r)

    # Cap at 5 after filtering (was: 5 LIMIT in SQL, now we filter then cap).
    filtered = filtered[:5]

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
        for r in filtered
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

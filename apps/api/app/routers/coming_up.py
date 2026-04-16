"""Coming Up — daily engagement loop on home screen.

GET /coming-up — aggregates upcoming items across credentials, regulation
updates, PSC checklist progress, and compliance log gaps. Returns a flat
list of items with type, urgency, vessel context, and deep-link target.

Read-only aggregation across existing tables. No new schema.
"""

import json
import uuid as _uuid
from datetime import date, datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.auth.deps import get_current_user
from app.auth.schemas import CurrentUser
from app.db import get_pool

router = APIRouter(prefix="/coming-up", tags=["coming-up"])


# ── Models ────────────────────────────────────────────────────────────────

ItemType = Literal[
    "credential_expiry",      # MMC/STCW/medical/TWIC expiring soon
    "coi_expiry",             # Vessel COI expiration approaching
    "regulation_update",      # Recent regulation changes affecting user
    "psc_checklist_progress", # Incomplete PSC checklist
    "log_gap",                # Long since last compliance log entry
]

Urgency = Literal["high", "medium", "low"]


class ComingUpItem(BaseModel):
    type: ItemType
    urgency: Urgency
    title: str
    description: str
    target_url: str            # Deep-link to the relevant page
    vessel_id: str | None = None
    vessel_name: str | None = None
    days_until: int | None = None  # Negative if overdue


class ComingUpResponse(BaseModel):
    items: list[ComingUpItem]
    generated_at: str


# ── Helpers ────────────────────────────────────────────────────────────────


def _credential_urgency(days_left: int) -> Urgency:
    if days_left < 0 or days_left <= 7:
        return "high"
    if days_left <= 30:
        return "medium"
    return "low"


def _coi_urgency(days_left: int) -> Urgency:
    if days_left < 0 or days_left <= 14:
        return "high"
    if days_left <= 60:
        return "medium"
    return "low"


def _checklist_urgency(progress_pct: float, days_old: int) -> Urgency:
    """Older + less complete = more urgent."""
    if days_old > 90 and progress_pct < 0.5:
        return "high"
    if days_old > 30 or progress_pct < 0.3:
        return "medium"
    return "low"


def _format_days(days: int) -> str:
    """Human-friendly day count."""
    if days < 0:
        n = abs(days)
        return f"{n} day{'s' if n != 1 else ''} ago"
    if days == 0:
        return "today"
    if days == 1:
        return "tomorrow"
    return f"in {days} days"


# ── Endpoint ───────────────────────────────────────────────────────────────


@router.get("", response_model=ComingUpResponse)
async def get_coming_up(
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> ComingUpResponse:
    """Aggregate upcoming items for the user across all surfaces."""
    pool = await get_pool()
    user_id = _uuid.UUID(user.user_id)
    today = date.today()
    items: list[ComingUpItem] = []

    # ── 1. Credential expiry (≤ 90 days or expired) ──────────────────────
    cred_rows = await pool.fetch(
        """
        SELECT id, credential_type, title, expiry_date
        FROM user_credentials
        WHERE user_id = $1
          AND expiry_date IS NOT NULL
          AND expiry_date <= CURRENT_DATE + INTERVAL '90 days'
        ORDER BY expiry_date ASC
        """,
        user_id,
    )
    for r in cred_rows:
        days_left = (r["expiry_date"] - today).days
        verb = "expired" if days_left < 0 else "expires"
        items.append(ComingUpItem(
            type="credential_expiry",
            urgency=_credential_urgency(days_left),
            title=f"{r['title']} {verb} {_format_days(days_left)}",
            description=f"Credential type: {r['credential_type'].upper()}",
            target_url="/credentials",
            days_until=days_left,
        ))

    # ── 2. COI expiry (extracted from vessel_documents) ──────────────────
    # Pull confirmed COI documents and check expiration_date in extracted_data
    doc_rows = await pool.fetch(
        """
        SELECT vd.vessel_id, vd.extracted_data, v.name AS vessel_name
        FROM vessel_documents vd
        JOIN vessels v ON v.id = vd.vessel_id
        WHERE vd.user_id = $1
          AND vd.document_type = 'coi'
          AND vd.extraction_status = 'confirmed'
        """,
        user_id,
    )
    for r in doc_rows:
        ed = r["extracted_data"]
        if isinstance(ed, str):
            try:
                ed = json.loads(ed)
            except (ValueError, TypeError):
                continue
        if not isinstance(ed, dict):
            continue
        exp_str = ed.get("expiration_date") or ed.get("expiry_date")
        if not exp_str or not isinstance(exp_str, str):
            continue
        # Parse common date formats
        exp_date = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d %b %Y", "%B %d, %Y"):
            try:
                exp_date = datetime.strptime(exp_str.strip(), fmt).date()
                break
            except ValueError:
                continue
        if not exp_date:
            continue
        days_left = (exp_date - today).days
        if days_left > 90:  # Only surface if within 90 days
            continue
        verb = "expired" if days_left < 0 else "expires"
        items.append(ComingUpItem(
            type="coi_expiry",
            urgency=_coi_urgency(days_left),
            title=f"COI for {r['vessel_name']} {verb} {_format_days(days_left)}",
            description=f"Certificate of Inspection on file expires {exp_date.isoformat()}",
            target_url=f"/account/vessel/{r['vessel_id']}",
            vessel_id=str(r["vessel_id"]),
            vessel_name=r["vessel_name"],
            days_until=days_left,
        ))

    # ── 3. PSC checklist progress (incomplete checklists) ────────────────
    cl_rows = await pool.fetch(
        """
        SELECT pc.vessel_id, pc.items, pc.checked_indices, pc.generated_at,
               v.name AS vessel_name
        FROM psc_checklists pc
        JOIN vessels v ON v.id = pc.vessel_id
        WHERE pc.user_id = $1
        """,
        user_id,
    )
    for r in cl_rows:
        items_raw = r["items"]
        if isinstance(items_raw, str):
            try:
                items_raw = json.loads(items_raw)
            except (ValueError, TypeError):
                continue
        if not isinstance(items_raw, list):
            continue
        total = len(items_raw)
        if total == 0:
            continue
        checked = len(r["checked_indices"] or [])
        if checked >= total:
            continue  # Fully complete — don't surface
        progress_pct = checked / total
        gen_at = r["generated_at"]
        days_old = (datetime.now(timezone.utc) - gen_at).days if gen_at else 0
        items.append(ComingUpItem(
            type="psc_checklist_progress",
            urgency=_checklist_urgency(progress_pct, days_old),
            title=f"PSC checklist for {r['vessel_name']} is {checked}/{total} complete",
            description=f"Generated {days_old} day{'s' if days_old != 1 else ''} ago",
            target_url="/psc-checklist",
            vessel_id=str(r["vessel_id"]),
            vessel_name=r["vessel_name"],
            days_until=None,
        ))

    # ── 4. Compliance log gap (no entries in last 30 days for any vessel) ─
    vessel_rows = await pool.fetch(
        """
        SELECT v.id AS vessel_id, v.name AS vessel_name,
               (
                 SELECT MAX(entry_date) FROM compliance_logs cl
                 WHERE cl.user_id = $1 AND cl.vessel_id = v.id
               ) AS last_entry_date
        FROM vessels v
        WHERE v.user_id = $1
        """,
        user_id,
    )
    for r in vessel_rows:
        last_entry = r["last_entry_date"]
        if last_entry is None:
            continue  # Never logged anything — don't pester (could be intentional)
        days_since = (today - last_entry).days
        if days_since < 30:
            continue
        # Surface as a soft prompt
        items.append(ComingUpItem(
            type="log_gap",
            urgency="low",
            title=f"Last compliance log for {r['vessel_name']} was {days_since} days ago",
            description="Consider logging recent drills, inspections, or maintenance",
            target_url="/log",
            vessel_id=str(r["vessel_id"]),
            vessel_name=r["vessel_name"],
            days_until=-days_since,
        ))

    # ── 5. Recent regulation updates (last 14 days) ──────────────────────
    notif_rows = await pool.fetch(
        """
        SELECT title, body, source, created_at
        FROM notifications
        WHERE notification_type = 'regulation_update'
          AND is_active = true
          AND created_at > NOW() - INTERVAL '14 days'
        ORDER BY created_at DESC
        LIMIT 3
        """,
    )
    for r in notif_rows:
        days_ago = (datetime.now(timezone.utc) - r["created_at"]).days
        items.append(ComingUpItem(
            type="regulation_update",
            urgency="medium" if days_ago <= 7 else "low",
            title=r["title"],
            description=r["body"][:120] if r["body"] else "",
            target_url="/",  # Open chat to ask about it
            days_until=-days_ago if days_ago > 0 else 0,
        ))

    # ── Sort: high urgency first, then by days_until ascending ─────────────
    urgency_rank = {"high": 0, "medium": 1, "low": 2}
    items.sort(key=lambda i: (
        urgency_rank.get(i.urgency, 3),
        i.days_until if i.days_until is not None else 999,
    ))

    return ComingUpResponse(
        items=items,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )

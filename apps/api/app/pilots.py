"""Wheelhouse pilots (growth plan step 4, 2026-10-14).

A workspace's trial ends at workspaces.trial_ends_at, or 30 days after it was
created when that is NULL (TRIAL_END_SQL; the daily state machine in
app/tasks.py and the API's trial_ends_at both read it).

A pilot is a longer trial handed out with a link: /register?next=/workspaces
&src=pilot-<code>. The first-touch attribution keeps src; when that user
creates a workspace, apply_signup_pilot() sets trial_ends_at from the code's
trial_days. An admin can also apply a code, or any number of days, to an
existing workspace (routers/admin_pilots.py).
"""
from __future__ import annotations

import re
import uuid

STANDARD_TRIAL_DAYS = 30
REMINDER_DAYS_BEFORE_END = 5
TRIAL_END_SQL = "COALESCE(w.trial_ends_at, w.created_at + interval '30 days')"
CODE_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,38}$")
SRC_PREFIX = "pilot-"


def normalize_code(code: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", code.strip().lower()).strip("-")[:39]


def signup_link(code: str) -> str:
    return f"https://regknots.com/register?next=/workspaces&src={SRC_PREFIX}{code}"


def code_from_src(src: str | None) -> str | None:
    if src and src.lower().startswith(SRC_PREFIX):
        return src[len(SRC_PREFIX):].lower() or None
    return None


async def apply_signup_pilot(conn, workspace_id: uuid.UUID, owner_id: uuid.UUID) -> dict | None:
    """Give a new workspace its owner's pilot trial, if they signed up from an
    active pilot link. Returns {"code", "trial_days"} when applied."""
    src = await conn.fetchval("SELECT signup_attribution->>'src' FROM users WHERE id = $1", owner_id)
    code = code_from_src(src)
    if not code:
        return None
    days = await conn.fetchval("SELECT trial_days FROM pilot_codes WHERE code = $1 AND active", code)
    if not days:
        return None
    await conn.execute(
        "UPDATE workspaces SET trial_ends_at = created_at + make_interval(days => $2), updated_at = now() "
        "WHERE id = $1",
        workspace_id, days,
    )
    return {"code": code, "trial_days": days}

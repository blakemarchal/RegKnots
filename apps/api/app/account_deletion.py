"""2026-09-29 — delete an account and everything that belongs to it.

Shared by the self-serve route (POST /auth/delete-account) and the owner-only
admin route (DELETE /admin/users/{id}).

Order matters:
  1. Stripe. The user's own subscription and the subscription of every
     workspace they own are canceled immediately. If Stripe refuses, nothing is
     deleted, so nobody keeps being charged for an account that is gone. (The
     admin delete used to skip this step, leaving the subscription billing.)
  2. Collect the uploaded files (vessel documents, documents of owned
     workspaces) before their rows cascade away.
  3. One transaction: delete the owned workspaces (workspaces.owner_user_id is
     ON DELETE RESTRICT), then the user. Every other table cascades or sets its
     user column to NULL; billing_events keeps the payment with user_id NULL
     (migration 0118), so revenue and partner accruals stand.
  4. Remove the files. Only paths inside settings.upload_dir are touched, and a
     file that can't be removed is logged, not fatal.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import stripe

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class DeletionSummary:
    email: str
    subscriptions_canceled: int = 0
    workspaces_deleted: list[dict] = field(default_factory=list)
    files_removed: int = 0


async def shared_workspaces_owned(pool, uid: uuid.UUID) -> list[str]:
    """Names of workspaces this user owns that other people are members of.

    Deleting the owner deletes the workspace, which would take the crew's
    shared vessel, documents and access with it, so the self-serve route
    refuses until ownership is handed over or the crew is removed.
    """
    rows = await pool.fetch(
        """
        SELECT w.name FROM workspaces w
        WHERE w.owner_user_id = $1
          AND w.status <> 'archived'
          AND EXISTS (
              SELECT 1 FROM workspace_members m
              WHERE m.workspace_id = w.id AND m.user_id <> $1
          )
        ORDER BY w.name
        """,
        uid,
    )
    return [r["name"] for r in rows]


def _cancel_subscription(sub_id: str) -> bool:
    """Cancel one Stripe subscription now. False when there was nothing to stop."""
    stripe.api_key = settings.stripe_secret_key
    try:
        sub = stripe.Subscription.retrieve(sub_id)
    except stripe.InvalidRequestError as exc:
        if getattr(exc, "code", None) == "resource_missing":
            return False
        raise
    if sub.status in ("canceled", "incomplete_expired"):
        return False
    stripe.Subscription.cancel(sub_id)
    return True


def _remove_file(path: str, root: Path) -> bool:
    try:
        p = Path(path).resolve()
        if not p.is_relative_to(root):
            logger.warning("account deletion: skipped a file outside the upload dir: %s", path)
            return False
        if p.is_file():
            p.unlink()
            return True
    except OSError:
        logger.exception("account deletion: could not remove %s", path)
    return False


async def delete_account(pool, uid: uuid.UUID) -> DeletionSummary:
    user = await pool.fetchrow(
        "SELECT email, stripe_subscription_id FROM users WHERE id = $1", uid,
    )
    if user is None:
        raise LookupError("user not found")
    owned = await pool.fetch(
        "SELECT id, name, status, stripe_subscription_id FROM workspaces WHERE owner_user_id = $1",
        uid,
    )
    owned_ids = [w["id"] for w in owned]
    summary = DeletionSummary(email=user["email"])

    # 1. Stripe. Raises (and deletes nothing) if a live subscription can't be canceled.
    sub_ids = [user["stripe_subscription_id"], *(w["stripe_subscription_id"] for w in owned)]
    for sub_id in filter(None, sub_ids):
        if await asyncio.to_thread(_cancel_subscription, sub_id):
            summary.subscriptions_canceled += 1

    # 2. Files whose rows are about to go: documents the user uploaded, documents
    # on vessels that go with the user or with an owned workspace, the owned
    # workspaces' company documents, and the documents attached in chat (2026-10-05).
    file_rows = await pool.fetch(
        """
        SELECT file_path FROM vessel_documents
        WHERE user_id = $1
           OR vessel_id IN (SELECT id FROM vessels WHERE user_id = $1 OR workspace_id = ANY($2::uuid[]))
        UNION
        SELECT file_path FROM workspace_documents WHERE workspace_id = ANY($2::uuid[])
        UNION
        SELECT file_path FROM user_documents WHERE user_id = $1
        """,
        uid, owned_ids,
    )

    # 3. Rows.
    async with pool.acquire() as conn:
        async with conn.transaction():
            if owned_ids:
                await conn.execute("DELETE FROM workspaces WHERE id = ANY($1::uuid[])", owned_ids)
            await conn.execute("DELETE FROM users WHERE id = $1", uid)
    summary.workspaces_deleted = [
        {"id": str(w["id"]), "name": w["name"], "prior_status": w["status"]} for w in owned
    ]

    # 4. Files.
    root = Path(settings.upload_dir).resolve()
    summary.files_removed = sum(_remove_file(r["file_path"], root) for r in file_rows if r["file_path"])
    return summary

"""add workspace_id to vessels for crew-tier vessel scope

Revision ID: 0080
Revises: 0079
Create Date: 2026-05-04

Sprint D6.55 — Wheelhouse vessel scope.

Until now `vessels` was strictly user-scoped (one user, many personal
vessels). Workspaces have no concept of "their" vessel — which means
crew members in a workspace can't pick the boat for a chat: they
either see no vessels (if they have no personal account) or see their
personal vessels (which contaminates a workspace chat about a
different boat).

This migration introduces the workspace-scoped vessel:
  - workspace_id  nullable FK to workspaces — if set, this is a
                  workspace vessel; user_id is just the creator
  - When workspace_id IS NULL, behavior is exactly as before
    (personal vessel, user-scoped)
  - When workspace_id IS NOT NULL, the vessel belongs to the workspace;
    any member can read it, only Owner/Admin can edit/delete it
    (enforced in API layer)

Backfill: for every existing workspace, create a workspace vessel
named after the workspace and tied to the owner. This way the
workspace already has a vessel by the time the UI starts asking for
one, and existing crew (Bryanna, Karynn, etc.) immediately see a
working vessel context.

Note: keep user_id NOT NULL — it's still the creator/owner reference,
just no longer the scope key by itself.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0080"
down_revision: Union[str, None] = "0079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE vessels
        ADD COLUMN IF NOT EXISTS workspace_id UUID
            REFERENCES workspaces(id) ON DELETE CASCADE
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS vessels_workspace_idx "
        "ON vessels(workspace_id) WHERE workspace_id IS NOT NULL"
    )

    # Backfill: one default vessel per existing workspace, owned by the
    # workspace owner, named after the workspace. INSERT ... SELECT so
    # this is idempotent if re-run (we filter out workspaces that already
    # have a vessel).
    op.execute("""
        INSERT INTO vessels (
            user_id, workspace_id, name, vessel_type,
            flag_state, route_types, cargo_types, created_at, updated_at
        )
        SELECT
            w.owner_user_id,
            w.id,
            w.name,
            'unknown',
            'Unknown',
            ARRAY['coastal']::TEXT[],
            ARRAY[]::TEXT[],
            now(),
            now()
        FROM workspaces w
        WHERE NOT EXISTS (
            SELECT 1 FROM vessels v WHERE v.workspace_id = w.id
        )
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS vessels_workspace_idx")
    op.execute("ALTER TABLE vessels DROP COLUMN IF EXISTS workspace_id")

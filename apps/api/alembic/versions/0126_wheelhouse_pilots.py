"""Wheelhouse pilots: a per-workspace trial end and pilot codes

Revision ID: 0126
Revises: 0125
Create Date: 2026-10-14

Growth plan step 4 (docs/specs/growth-plan-2026-10-14.md).

  workspaces.trial_ends_at  NULL = the standard trial (created_at + 30 days,
                            as before); set for a pilot (90 days) or when an
                            admin extends a trial. The daily state machine
                            reads COALESCE(trial_ends_at, created_at + 30 days).
  pilot_codes               a pilot link is /register?next=/workspaces&src=pilot-<code>;
                            a workspace created by an owner who signed up from
                            an active code gets that code's trial_days.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0126"
down_revision: Union[str, None] = "0125"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE workspaces ADD COLUMN trial_ends_at TIMESTAMPTZ")
    op.execute(
        """
        CREATE TABLE pilot_codes (
            code        TEXT PRIMARY KEY CHECK (code ~ '^[a-z0-9][a-z0-9-]{1,38}$'),
            label       TEXT NOT NULL,
            trial_days  INTEGER NOT NULL DEFAULT 90 CHECK (trial_days BETWEEN 1 AND 365),
            active      BOOLEAN NOT NULL DEFAULT TRUE,
            notes       TEXT,
            created_by  UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS pilot_codes")
    op.execute("ALTER TABLE workspaces DROP COLUMN IF EXISTS trial_ends_at")

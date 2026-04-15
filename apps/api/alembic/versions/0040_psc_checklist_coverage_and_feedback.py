"""add coverage metadata to psc_checklists + create checklist_feedback table

Revision ID: 0040
Revises: 0039
Create Date: 2026-04-15

Two changes supporting checklist trust and data moat work:

1. Adds `coverage` JSONB column to psc_checklists storing the AI's rationale
   for included/omitted categories. Surfaced in the UI as a transparency
   statement ("This checklist covers 7 of 9 categories; ISPS Security was
   omitted because...").

2. Creates `checklist_feedback` table — silent data capture for every user
   action on PSC checklist items (add, edit, delete). Not yet consumed for
   any feature; captures ground-truth signal for later per-vessel learning.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0040"
down_revision: Union[str, None] = "0039"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE psc_checklists ADD COLUMN coverage JSONB"
    )

    op.execute(
        """
        CREATE TABLE checklist_feedback (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vessel_id       UUID NOT NULL REFERENCES vessels(id) ON DELETE CASCADE,
            checklist_id    UUID NOT NULL REFERENCES psc_checklists(id) ON DELETE CASCADE,
            action_type     TEXT NOT NULL CHECK (action_type IN ('add', 'edit', 'delete')),
            original_item   JSONB,
            final_item      JSONB,
            item_index      INTEGER,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_checklist_feedback_vessel ON checklist_feedback(vessel_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_checklist_feedback_user ON checklist_feedback(user_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_checklist_feedback_user")
    op.execute("DROP INDEX IF EXISTS idx_checklist_feedback_vessel")
    op.execute("DROP TABLE IF EXISTS checklist_feedback")
    op.execute("ALTER TABLE psc_checklists DROP COLUMN IF EXISTS coverage")

"""create psc_checklists table for persistent per-vessel PSC checklists

Revision ID: 0039
Revises: 0038
Create Date: 2026-04-14

One checklist per (user, vessel) — regenerating replaces the existing row.
Stores items as JSONB array and tracks which indices are checked off so
users can resume a partially-completed inspection prep across sessions.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0039"
down_revision: Union[str, None] = "0038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE psc_checklists (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id          UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vessel_id        UUID NOT NULL REFERENCES vessels(id) ON DELETE CASCADE,
            items            JSONB NOT NULL,
            checked_indices  INTEGER[] NOT NULL DEFAULT '{}',
            generated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            UNIQUE (user_id, vessel_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_psc_checklists_vessel ON psc_checklists(vessel_id)"
    )
    op.execute(
        """
        CREATE TRIGGER psc_checklists_updated_at
            BEFORE UPDATE ON psc_checklists
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS psc_checklists_updated_at ON psc_checklists")
    op.execute("DROP TABLE IF EXISTS psc_checklists")

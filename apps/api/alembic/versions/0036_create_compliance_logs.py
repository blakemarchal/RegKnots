"""create compliance_logs table for voyage/compliance logging

Revision ID: 0036
Revises: 0035
Create Date: 2026-04-13

Structured log entries: date, vessel, category, free-text notes.
Vessel-attached, timestamped, user-owned.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0036"
down_revision: Union[str, None] = "0035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE compliance_logs (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vessel_id   UUID REFERENCES vessels(id) ON DELETE SET NULL,
            entry_date  DATE NOT NULL DEFAULT CURRENT_DATE,
            category    TEXT NOT NULL CHECK (
                category IN (
                    'safety_drill', 'inspection', 'maintenance',
                    'incident', 'navigation', 'cargo', 'crew',
                    'environmental', 'psc', 'general'
                )
            ),
            entry       TEXT NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_compliance_logs_user ON compliance_logs(user_id, entry_date DESC)"
    )
    op.execute(
        "CREATE INDEX idx_compliance_logs_vessel ON compliance_logs(vessel_id, entry_date DESC) WHERE vessel_id IS NOT NULL"
    )
    op.execute(
        """
        CREATE TRIGGER compliance_logs_updated_at
            BEFORE UPDATE ON compliance_logs
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS compliance_logs_updated_at ON compliance_logs")
    op.execute("DROP TABLE IF EXISTS compliance_logs")

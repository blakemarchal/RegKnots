"""create admin_audit_log table

Revision ID: 0041
Revises: 0040
Create Date: 2026-04-15

Records every destructive or sensitive admin action for accountability
and debugging. Every mutation through the admin panel writes a row.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0041"
down_revision: Union[str, None] = "0040"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE admin_audit_log (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            admin_user_id   UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            admin_email     TEXT NOT NULL,
            action          TEXT NOT NULL,
            target_id       TEXT,
            details         JSONB,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_admin_audit_log_created ON admin_audit_log(created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_audit_log")

"""admin_audit_log keeps its rows when an admin account is deleted

Revision ID: 0127
Revises: 0126
Create Date: 2026-10-16

Security review 2026-10-16 (docs/sprint-audits/security-review-2026-10-16.md):
admin_audit_log.admin_user_id was NOT NULL with ON DELETE CASCADE (0041), so
deleting an admin erased the record of what they did. The column is now
nullable with ON DELETE SET NULL; admin_email keeps who it was.

The live constraint was read before writing this (2026-10-16):
admin_audit_log_admin_user_id_fkey FOREIGN KEY (admin_user_id) REFERENCES
users(id) ON DELETE CASCADE.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0127"
down_revision: Union[str, None] = "0126"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE admin_audit_log DROP CONSTRAINT IF EXISTS admin_audit_log_admin_user_id_fkey")
    op.execute("ALTER TABLE admin_audit_log ALTER COLUMN admin_user_id DROP NOT NULL")
    op.execute(
        "ALTER TABLE admin_audit_log ADD CONSTRAINT admin_audit_log_admin_user_id_fkey "
        "FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE admin_audit_log DROP CONSTRAINT IF EXISTS admin_audit_log_admin_user_id_fkey")
    op.execute("DELETE FROM admin_audit_log WHERE admin_user_id IS NULL")
    op.execute("ALTER TABLE admin_audit_log ALTER COLUMN admin_user_id SET NOT NULL")
    op.execute(
        "ALTER TABLE admin_audit_log ADD CONSTRAINT admin_audit_log_admin_user_id_fkey "
        "FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE CASCADE"
    )

"""create support_tickets table

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-07

Persists support tickets so the admin dashboard can view and reply to them
in-app via Resend instead of relying on the Gmail forward.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE support_tickets (
            id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            user_email  TEXT NOT NULL,
            user_name   TEXT,
            subject     TEXT NOT NULL,
            message     TEXT NOT NULL,
            status      TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'replied', 'closed')),
            admin_reply TEXT,
            replied_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX idx_support_tickets_user ON support_tickets(user_id)")
    op.execute("CREATE INDEX idx_support_tickets_status ON support_tickets(status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_support_tickets_status")
    op.execute("DROP INDEX IF EXISTS idx_support_tickets_user")
    op.execute("DROP TABLE IF EXISTS support_tickets")

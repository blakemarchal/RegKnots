"""create user_credentials table for personal maritime credentials

Revision ID: 0035
Revises: 0034
Create Date: 2026-04-13

Tracks personal credentials (MMC, STCW endorsements, medical cert,
TWIC, etc.) with expiry dates for reminder notifications.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0035"
down_revision: Union[str, None] = "0034"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE user_credentials (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            credential_type   TEXT NOT NULL CHECK (
                credential_type IN ('mmc', 'stcw', 'medical', 'twic', 'other')
            ),
            title             TEXT NOT NULL,
            credential_number TEXT,
            issuing_authority TEXT,
            issue_date        DATE,
            expiry_date       DATE,
            notes             TEXT,
            reminder_sent_90  BOOLEAN NOT NULL DEFAULT FALSE,
            reminder_sent_30  BOOLEAN NOT NULL DEFAULT FALSE,
            reminder_sent_7   BOOLEAN NOT NULL DEFAULT FALSE,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_user_credentials_user ON user_credentials(user_id)"
    )
    op.execute(
        "CREATE INDEX idx_user_credentials_expiry ON user_credentials(expiry_date) WHERE expiry_date IS NOT NULL"
    )
    op.execute(
        """
        CREATE TRIGGER user_credentials_updated_at
            BEFORE UPDATE ON user_credentials
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS user_credentials_updated_at ON user_credentials")
    op.execute("DROP TABLE IF EXISTS user_credentials")

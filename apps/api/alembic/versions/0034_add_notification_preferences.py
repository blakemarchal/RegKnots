"""add notification_preferences JSONB column to users

Revision ID: 0034
Revises: 0033
Create Date: 2026-04-13

Stores per-user email notification settings:
  {
    "cert_expiry_reminders": true,
    "cert_expiry_days": [90, 30, 7],
    "reg_change_digest": true,
    "reg_digest_frequency": "weekly"
  }
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_DEFAULT = '{"cert_expiry_reminders": true, "cert_expiry_days": [90, 30, 7], "reg_change_digest": true, "reg_digest_frequency": "weekly"}'


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE users
        ADD COLUMN notification_preferences JSONB NOT NULL DEFAULT '{_DEFAULT}'::jsonb
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS notification_preferences")

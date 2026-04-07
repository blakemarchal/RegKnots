"""add founding_email_sent column to users

Revision ID: 0028
Revises: 0027
Create Date: 2026-04-07

Tracks whether the founding member announcement email has been delivered to
each pilot user so the admin send button can avoid double-sends.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN founding_email_sent BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS founding_email_sent")

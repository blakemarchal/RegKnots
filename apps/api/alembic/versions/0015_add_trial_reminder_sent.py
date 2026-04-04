"""add trial_reminder_sent flag to users

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-03

Tracks whether we've sent the trial expiring reminder email.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users ADD COLUMN trial_reminder_sent BOOLEAN NOT NULL DEFAULT FALSE"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users DROP COLUMN trial_reminder_sent"
    ))

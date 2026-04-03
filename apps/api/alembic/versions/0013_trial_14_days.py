"""extend pilot trial from 7 to 14 days

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-03

Changes the default trial_ends_at from 7 days to 14 days and updates
existing users who still have the 7-day window.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users ALTER COLUMN trial_ends_at "
        "SET DEFAULT (NOW() + INTERVAL '14 days')"
    ))
    op.execute(sa.text(
        "UPDATE users SET trial_ends_at = created_at + INTERVAL '14 days' "
        "WHERE trial_ends_at = created_at + INTERVAL '7 days'"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users ALTER COLUMN trial_ends_at "
        "SET DEFAULT (NOW() + INTERVAL '7 days')"
    ))
    op.execute(sa.text(
        "UPDATE users SET trial_ends_at = created_at + INTERVAL '7 days' "
        "WHERE trial_ends_at = created_at + INTERVAL '14 days'"
    ))

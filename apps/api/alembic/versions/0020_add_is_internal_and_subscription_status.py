"""add is_internal column and expand subscription_status check

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-05

Adds is_internal boolean to users table for filtering internal accounts
from admin analytics. Also expands subscription_status CHECK to include
'canceling' and 'paused'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_internal column
    op.execute(sa.text(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT FALSE"
    ))

    # Mark known internal accounts
    op.execute(sa.text(
        "UPDATE users SET is_internal = TRUE "
        "WHERE email IN ('blakemarchal@gmail.com', 'kdmarchal@gmail.com', 'test@regknots.com')"
    ))
    op.execute(sa.text(
        "UPDATE users SET is_internal = TRUE WHERE email LIKE 'blakemarchal+%'"
    ))

    # Expand subscription_status CHECK to include 'canceling' and 'paused'
    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_status_check "
        "CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled', 'canceling', 'paused'))"
    ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS is_internal"))
    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_status_check "
        "CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled'))"
    ))

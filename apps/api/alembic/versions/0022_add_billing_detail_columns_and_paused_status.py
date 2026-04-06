"""add billing detail columns and paused status

Revision ID: 0022
Revises: 0021
Create Date: 2026-04-05

Adds cancel_at_period_end, current_period_end, and billing_interval
to the users table. Re-adds 'paused' to subscription_status CHECK.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("cancel_at_period_end", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("users", sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("billing_interval", sa.Text(), nullable=True))

    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_status_check "
        "CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled', 'canceling', 'paused'))"
    ))


def downgrade() -> None:
    op.drop_column("users", "billing_interval")
    op.drop_column("users", "current_period_end")
    op.drop_column("users", "cancel_at_period_end")

    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_status_check "
        "CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled', 'canceling'))"
    ))

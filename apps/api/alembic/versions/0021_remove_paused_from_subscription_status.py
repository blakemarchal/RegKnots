"""remove paused from subscription_status check

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-05

Removes 'paused' from the subscription_status CHECK constraint.
We don't support pausing — users cancel and re-subscribe.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_status_check "
        "CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled', 'canceling'))"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_status_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_status_check "
        "CHECK (subscription_status IN ('active', 'inactive', 'past_due', 'canceled', 'canceling', 'paused'))"
    ))

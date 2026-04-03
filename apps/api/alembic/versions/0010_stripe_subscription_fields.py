"""add stripe subscription tracking fields to users

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-02

Adds stripe_subscription_id, trial_ends_at (default 7 days from now),
and message_count to support subscription gating.  Also updates the
subscription_tier CHECK to include 'pro'.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users ADD COLUMN stripe_subscription_id TEXT UNIQUE"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD COLUMN trial_ends_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '7 days')"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD COLUMN message_count INTEGER NOT NULL DEFAULT 0"
    ))
    # Expand tier check to include 'pro'
    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_tier_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_tier_check "
        "CHECK (subscription_tier IN ('free', 'pro', 'solo', 'fleet', 'enterprise'))"
    ))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS stripe_subscription_id"))
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS trial_ends_at"))
    op.execute(sa.text("ALTER TABLE users DROP COLUMN IF EXISTS message_count"))
    op.execute(sa.text(
        "ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_tier_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_tier_check "
        "CHECK (subscription_tier IN ('free', 'solo', 'fleet', 'enterprise'))"
    ))

"""add mate+captain tiers, referral_source, monthly_message_count

Revision ID: 0050
Revises: 0049
Create Date: 2026-04-24

Sprint D6.1 — pricing model restructure from the single $39 Pro plan to
two-tier Mate ($19.99/mo, 100-msg cap) + Captain ($39.99/mo, unlimited).

Schema changes:
  1. Expand subscription_tier CHECK to allow 'mate' and 'captain'.
     Keeps existing values (free/pro/solo/fleet/enterprise) for backward
     compat with any legacy subscription records — we have zero paying
     users at migration time so there's nothing to grandfather.
  2. Reduce trial_ends_at default from 14 days to 7 days (new signups).
     Existing users' trial_ends_at values are unchanged.
  3. Add monthly_message_count + message_cycle_started_at for Mate cap
     enforcement. Separate from the lifetime `message_count` column so
     the legacy 50-message trial gate keeps working unchanged.
  4. Add referral_source column (nullable, indexed) for charity partner
     attribution. Extensible — any string key works, not hardcoded to
     Women Offshore.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Expand subscription_tier CHECK to include 'mate' and 'captain'.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_tier_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_tier_check "
        "CHECK (subscription_tier IN "
        "('free', 'pro', 'solo', 'fleet', 'enterprise', 'mate', 'captain'))"
    )

    # 2. Change trial default: 14 days → 7 days for new users.
    op.execute(
        "ALTER TABLE users ALTER COLUMN trial_ends_at "
        "SET DEFAULT NOW() + INTERVAL '7 days'"
    )

    # 3. Mate 100-msg monthly cap tracking.
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "monthly_message_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "message_cycle_started_at TIMESTAMPTZ NOT NULL DEFAULT NOW()"
    )

    # 4. Charity referral tracking.
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS referral_source TEXT")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_referral_source "
        "ON users (referral_source) WHERE referral_source IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_users_referral_source")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS referral_source")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS message_cycle_started_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS monthly_message_count")
    op.execute(
        "ALTER TABLE users ALTER COLUMN trial_ends_at "
        "SET DEFAULT NOW() + INTERVAL '14 days'"
    )
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_tier_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_subscription_tier_check "
        "CHECK (subscription_tier IN "
        "('free', 'pro', 'solo', 'fleet', 'enterprise'))"
    )

"""add cadet tier to subscription_tier CHECK constraint

Revision ID: 0097
Revises: 0096
Create Date: 2026-05-12

Sprint D6.91 — introduce Cadet tier ($9.99/mo, 25-msg cap) as the
entry-level paid plan. Cadet inherits all Mate features (Study Tools,
vessel dossier, credentials, etc.) — the only differentiator is the
monthly message cap (Cadet 25, Mate 100, Captain unlimited).

The actual cap is enforced in apps/api/app/routers/chat.py via the
existing monthly_message_count + message_cycle_started_at columns
already added in migration 0050. This migration only extends the
CHECK constraint so the Stripe webhook can persist 'cadet' to the
users.subscription_tier column.

Mirrors the same constraint-swap pattern used in 0090, 0094, and other
allowlist-expanding migrations.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0097"
down_revision: Union[str, None] = "0096"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Mirror the live constraint definition (queried from 0050) + the new
# 'cadet' value. Any future tier added by direct SQL on the VPS and
# not in this list would be dropped by the swap — verify against live
# before running.
_TIERS = ("free", "pro", "solo", "fleet", "enterprise", "mate", "captain", "cadet")


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_tier_check")
    tiers_sql = ", ".join(f"'{t}'" for t in _TIERS)
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT users_subscription_tier_check "
        f"CHECK (subscription_tier IN ({tiers_sql}))"
    )


def downgrade() -> None:
    # Re-tighten without 'cadet'. If any users were upgraded to Cadet
    # before rollback, this would fail — downgrade them to 'free'
    # first if you actually need to roll back.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_subscription_tier_check")
    tiers_without_cadet = [t for t in _TIERS if t != "cadet"]
    tiers_sql = ", ".join(f"'{t}'" for t in tiers_without_cadet)
    op.execute(
        f"ALTER TABLE users ADD CONSTRAINT users_subscription_tier_check "
        f"CHECK (subscription_tier IN ({tiers_sql}))"
    )

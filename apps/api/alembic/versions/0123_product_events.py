"""product_events: the funnel in our own database

Revision ID: 0123
Revises: 0122
Create Date: 2026-10-14

Growth plan step 1 (docs/specs/growth-plan-2026-10-14.md): one row per funnel
step, written by app/events.py: signup, first_question, paywall_hit,
checkout_started, checkout_completed. props holds the step's details (the
paywall reason, the plan, the signup source). user_id goes NULL when the
user is deleted, so the funnel counts survive account deletion; anon_id is
for events before signup (the anonymous first answer, step 2).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0123"
down_revision: Union[str, None] = "0122"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE product_events (
            id          BIGSERIAL PRIMARY KEY,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            event       TEXT NOT NULL,
            user_id     UUID REFERENCES users(id) ON DELETE SET NULL,
            anon_id     TEXT,
            props       JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute("CREATE INDEX ix_product_events_event_created ON product_events (event, created_at)")
    op.execute("CREATE INDEX ix_product_events_user ON product_events (user_id) WHERE user_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS product_events")

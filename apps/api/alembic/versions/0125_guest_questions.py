"""guest_questions: one free answer before signup

Revision ID: 0125
Revises: 0124
Create Date: 2026-10-14

Growth plan step 2 (docs/specs/growth-plan-2026-10-14.md). A visitor without
an account may ask one question (app/guest.py). The answer runs through the
normal chat pipeline in a conversation owned by an internal guest account;
this table records who asked, so the per-device, per-IP, daily and monthly
limits can be counted, and holds the claim: when the visitor signs up, the
conversation (and the vessel they picked) moves to their new account.

  device_hash / ip_hash  HMAC of the browser's random device id and the IP
                         (never stored in the clear)
  claim_hash             SHA-256 of the secret the visitor's browser keeps
  claimed_by             the account that claimed it; NULL until then
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0125"
down_revision: Union[str, None] = "0124"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE guest_questions (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            device_hash     TEXT NOT NULL,
            ip_hash         TEXT NOT NULL,
            conversation_id UUID REFERENCES conversations(id) ON DELETE SET NULL,
            vessel_id       UUID REFERENCES vessels(id) ON DELETE SET NULL,
            vessel_type     TEXT,
            page            TEXT,
            claim_hash      TEXT NOT NULL UNIQUE,
            claimed_by      UUID REFERENCES users(id) ON DELETE SET NULL,
            claimed_at      TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX ix_guest_questions_created ON guest_questions (created_at)")
    op.execute("CREATE INDEX ix_guest_questions_device ON guest_questions (device_hash, created_at)")
    op.execute("CREATE INDEX ix_guest_questions_ip ON guest_questions (ip_hash, created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS guest_questions")

"""add onboarding_completed_at to users

Revision ID: 0043
Revises: 0042
Create Date: 2026-04-16

Tracks completion of the new-user welcome wizard at /welcome (3-step
flow: vessel + optional COI + optional credential). Used by the
OnboardingGate on the chat home route to decide whether to redirect
brand-new users into the wizard.

Existing users (vessel_count > 0 or credential_count > 0) are
implicitly considered onboarded — the gate skips them regardless of
this flag.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0043"
down_revision: Union[str, None] = "0042"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN onboarding_completed_at TIMESTAMPTZ"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS onboarding_completed_at"
    )

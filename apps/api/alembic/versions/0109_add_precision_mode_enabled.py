"""add users.precision_mode_enabled column

Revision ID: 0109
Revises: 0108
Create Date: 2026-05-22

Sprint D6.97 (C) — per-user toggle for "Precision Mode" — a stricter
synthesis posture intended for compliance-officer use. When enabled,
the engine appends a STRICT_PRECISION_OVERLAY to the system prompt
that:

  - Refuses to gesture at regulatory claims that aren't grounded in
    the retrieved context (rather than the default soft hedge).
  - Reinforces the AUTHORITY HIERARCHY DECISION rules with a hard
    refusal floor when the binding authority for the user's vessel
    is ambiguous.

Per Blake (2026-05-22):
  - Default OFF for all tiers (NOT NULL default false)
  - Toggleable from the account page by all users regardless of tier
  - Karynn + Blake will test both modes before deciding whether to
    auto-on for Wheelhouse / Captain tiers

Mirrors the pattern of 0092_add_study_tools_enabled but simpler —
no persona-based backfill, no NULL state, no resolver.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0109"
down_revision: Union[str, None] = "0108"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "precision_mode_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "precision_mode_enabled")

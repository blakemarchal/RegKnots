"""add users.theme_preference

Revision ID: 0066
Revises: 0065
Create Date: 2026-05-01

Sprint D6.37 — captures dark/light theme preference per Madden's
feedback ("font and color scheme make extended use difficult — my
eyes hurt after using it for the past 45-60 minutes").

Allowed values:
  dark    Original navy + bone palette (current default)
  light   Bone background + navy text — high-contrast for daylight reading
  auto    Follow OS preference (prefers-color-scheme media query)

Nullable; NULL → "dark" (current behavior unchanged for existing users).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS theme_preference TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS theme_preference")

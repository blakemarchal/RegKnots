"""add share_token column to vessels for public compliance profiles

Revision ID: 0037
Revises: 0036
Create Date: 2026-04-13

Adds a unique share token to vessels for generating public shareable
compliance profile URLs.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0037"
down_revision: Union[str, None] = "0036"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vessels ADD COLUMN share_token TEXT UNIQUE"
    )
    op.execute(
        "CREATE INDEX idx_vessels_share_token ON vessels(share_token) WHERE share_token IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_vessels_share_token")
    op.execute("ALTER TABLE vessels DROP COLUMN IF EXISTS share_token")

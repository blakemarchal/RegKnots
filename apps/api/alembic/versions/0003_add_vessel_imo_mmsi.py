"""add imo_mmsi to vessels

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-31

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN imo_mmsi TEXT"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS imo_mmsi"))

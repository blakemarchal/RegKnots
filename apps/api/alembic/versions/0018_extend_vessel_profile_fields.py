"""extend vessels table with progressive profile fields

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-04

Adds fields for progressive vessel profiling — details learned from
chat conversations are saved back to the vessel record.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN subchapter TEXT"))
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN inspection_certificate_type TEXT"))
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN manning_requirement TEXT"))
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN key_equipment TEXT[]"))
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN route_limitations TEXT"))
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN additional_details JSONB DEFAULT '{}'"))
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN profile_enriched_at TIMESTAMPTZ"))


def downgrade() -> None:
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS subchapter"))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS inspection_certificate_type"))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS manning_requirement"))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS key_equipment"))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS route_limitations"))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS additional_details"))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN IF EXISTS profile_enriched_at"))

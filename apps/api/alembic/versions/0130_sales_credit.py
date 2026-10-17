"""Sales credit set by an admin (2026-10-17).

An account counts toward a salesperson when its first-touch signup link carried
their pilot code (signup_attribution.src = pilot-<code>). That misses a fleet
whose owner signed up without the link, or whose first touch was another
campaign. users.credited_sales_code lets an admin fix it from Admin > Sales:
a code credits that salesperson, '' credits no one, NULL (the default) falls
back to the link (app/sales_credit.py).

Revision ID: 0130
Revises: 0129
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0130"
down_revision: Union[str, None] = "0129"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN credited_sales_code TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS credited_sales_code")

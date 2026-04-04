"""add is_admin flag to users

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-03

Adds is_admin boolean column and sets admin accounts.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE"
    ))
    op.execute(sa.text(
        "UPDATE users SET is_admin = TRUE "
        "WHERE email IN ('test@regknots.com', 'blakemarchal@gmail.com')"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE users DROP COLUMN is_admin"
    ))

"""add chief_engineer to role CHECK constraint

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-06

Adds 'chief_engineer' to the users.role CHECK constraint.
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role = ANY (ARRAY['captain', 'mate', 'engineer', 'chief_engineer', 'other']))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role = ANY (ARRAY['captain', 'mate', 'engineer', 'other']))"
    )

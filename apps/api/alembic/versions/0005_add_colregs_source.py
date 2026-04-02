"""add colregs and isc to regulations source constraint

Revision ID: 0005
Revises: 0004
Create Date: 2026-03-31

Extends the source CHECK constraint on the regulations table to include
'colregs' (Navigation Rules / 72 COLREGS) and 'isc' (Marine Safety Circulars).
The existing values solas, marpol, stcw, mlc are already in the constraint
from migration 0001 — no data migration required.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALL_SOURCES = (
    "'cfr_33', 'cfr_46', 'cfr_49', "
    "'solas', 'marpol', 'stcw', 'mlc', "
    "'colregs', 'isc'"
)
_OLD_SOURCES = (
    "'cfr_33', 'cfr_46', 'cfr_49', "
    "'solas', 'marpol', 'stcw', 'mlc'"
)


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check"
    ))
    op.execute(sa.text(
        f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        f"CHECK (source IN ({_ALL_SOURCES}))"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check"
    ))
    op.execute(sa.text(
        f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        f"CHECK (source IN ({_OLD_SOURCES}))"
    ))

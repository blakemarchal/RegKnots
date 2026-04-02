"""add nvic to regulations source constraint

Revision ID: 0006
Revises: 0005
Create Date: 2026-03-31

Extends the source CHECK constraint on the regulations table to include
'nvic' (USCG Navigation and Vessel Inspection Circulars).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_SOURCES = (
    "'cfr_33', 'cfr_46', 'cfr_49', "
    "'solas', 'marpol', 'stcw', 'mlc', "
    "'colregs', 'isc', 'nvic'"
)
_OLD_SOURCES = (
    "'cfr_33', 'cfr_46', 'cfr_49', "
    "'solas', 'marpol', 'stcw', 'mlc', "
    "'colregs', 'isc'"
)


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check"
    ))
    op.execute(sa.text(
        f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        f"CHECK (source IN ({_NEW_SOURCES}))"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check"
    ))
    op.execute(sa.text(
        f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        f"CHECK (source IN ({_OLD_SOURCES}))"
    ))

"""add erg to regulations source constraint

Revision ID: 0014
Revises: 0013
Create Date: 2026-04-09

Adds 'erg' (Emergency Response Guidebook) to the allowed values in
regulations_source_check.
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
        "ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'nvic', 'solas', 'solas_supplement', 'erg'))"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check"
    ))
    op.execute(sa.text(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'nvic', 'solas', 'solas_supplement'))"
    ))

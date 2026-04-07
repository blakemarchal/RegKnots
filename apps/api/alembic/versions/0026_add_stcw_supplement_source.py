"""add stcw_supplement to regulations source CHECK constraint

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-07

Adds 'stcw_supplement' to the regulations.source CHECK constraint for the
STCW January 2025 Supplement ingestion.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'nvic', "
        "'solas', 'solas_supplement', 'stcw'))"
    )

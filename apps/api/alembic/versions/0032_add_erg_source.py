"""add erg to regulations source constraint

Revision ID: 0032
Revises: 0031
Create Date: 2026-04-10

Adds 'erg' (Emergency Response Guidebook 2024) to the allowed values in
regulations_source_check.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'ism', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )

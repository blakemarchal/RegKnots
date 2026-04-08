"""add ism to regulations source CHECK constraint

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-07

Adds 'ism' to the regulations.source CHECK constraint for the ISM Code
(International Safety Management Code) ingestion.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'ism', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )

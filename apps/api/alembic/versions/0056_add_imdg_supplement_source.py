"""add imdg_supplement source

Revision ID: 0056
Revises: 0055
Create Date: 2026-04-27

Sprint D6.12b — adds the imdg_supplement source for IMDG Code errata
and supplement publications. Currently covers the December 2025
errata (corrections to Amendment 42-24 adopted by MSC.556(108)).

Pure additive change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0056"
down_revision: Union[str, None] = "0055"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'imdg', "
        "'imdg_supplement', 'ism', 'ism_supplement', 'marpol', 'marpol_supplement', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'imdg', "
        "'ism', 'ism_supplement', 'marpol', 'marpol_supplement', 'nmc_checklist', "
        "'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )

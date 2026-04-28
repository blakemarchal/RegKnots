"""add amsa_mo source

Revision ID: 0059
Revises: 0058
Create Date: 2026-04-28

Sprint D6.20 — adds the amsa_mo source for Australian Maritime Safety
Authority Marine Orders. Australia's primary maritime regulatory
instruments. Each Order covers one operational topic; ~30 currently
in force. Phase-1 ingests ~25 of them (the operational surface for
Tier-1 vessel types).

License: CC BY 4.0 (Creative Commons Attribution 4.0 International).
Pure additive change to the source check constraint.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0059"
down_revision: Union[str, None] = "0058"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('amsa_mo', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'imdg', 'imdg_supplement', 'ism', 'ism_supplement', "
        "'marpol', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'imdg', 'imdg_supplement', 'ism', 'ism_supplement', "
        "'marpol', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )

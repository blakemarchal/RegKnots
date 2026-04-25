"""add uscg_msm source

Revision ID: 0051
Revises: 0050
Create Date: 2026-04-25

Sprint D6.4 — ingest USCG Marine Safety Manual (CIM 16000.X series).
Closes the PSC-enforcement corpus gap that Karynn surfaced 2026-04-22
("penalties if PSC inspector asks for VGM but I am missing some").

Additive only — preserves every source allowed at 0050.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0051"
down_revision: Union[str, None] = "0050"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin', 'usc_46', 'who_ihr'))"
    )

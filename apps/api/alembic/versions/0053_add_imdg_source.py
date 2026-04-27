"""add imdg source

Revision ID: 0053
Revises: 0052
Create Date: 2026-04-27

Sprint D6.12 — ingest IMDG Code 2024 Edition (Volumes 1 + 2,
Amendment 42-24). Mandatory under SOLAS Chapter VII Regulation 1.4
for the carriage of dangerous goods in packaged form by sea.

Pure additive change — preserves every source allowed at 0052.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'imdg', "
        "'ism', 'ism_supplement', 'marpol', 'marpol_supplement', 'nmc_checklist', "
        "'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'marpol', 'marpol_supplement', 'nmc_checklist', "
        "'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )

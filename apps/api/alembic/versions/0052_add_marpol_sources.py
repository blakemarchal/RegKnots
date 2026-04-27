"""add marpol + marpol_supplement sources

Revision ID: 0052
Revises: 0051
Create Date: 2026-04-27

Sprint D6.11 — ingest MARPOL Consolidated Edition 2022 plus its five
official supplements (errata Dec 2023, supplements May 2024, Aug 2025,
Jan 2026, Mar 2026). MARPOL is the International Convention for the
Prevention of Pollution from Ships, 1973, as modified by the 1978 and
1997 Protocols and subsequent amendments.

Pure additive change — preserves every source allowed at 0051.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0052"
down_revision: Union[str, None] = "0051"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'marpol', 'marpol_supplement', 'nmc_checklist', "
        "'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )

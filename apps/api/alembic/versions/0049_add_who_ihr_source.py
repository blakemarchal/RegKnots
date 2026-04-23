"""add who_ihr source

Revision ID: 0049
Revises: 0048
Create Date: 2026-04-23

Sprint D5.4 — ingest WHO International Health Regulations (2005, as
amended 2014/2022/2024). Covers port health and Ship Sanitation
Certificate (Annex 3 — SSCC / deratting). Karynn's 2026-04-22 session
surfaced a "deratting / sanitary inspection certificate" question that
hedged because IHR wasn't in corpus.

Additive only — preserves every source allowed at 0048.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin', 'usc_46', 'who_ihr'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin', 'usc_46'))"
    )

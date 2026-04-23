"""add usc_46 source

Revision ID: 0048
Revises: 0047
Create Date: 2026-04-23

Sprint D5.1 — ingest 46 USC Subtitle II (Vessels and Seamen) as a new
first-class RAG source. 46 USC is the statute (law passed by Congress);
46 CFR is the implementing regulation. Karynn's 2026-04-22 test session
surfaced labor/seamen questions (foreign articles, slop chest, crew
sign-on, wages) that hedge because the governing provisions are in
46 USC Chapters 71-77, not in 46 CFR. This migration adds the source
so ingest can populate it.

Additive only — preserves every source allowed at 0047.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0048"
down_revision: Union[str, None] = "0047"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin', 'usc_46'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin'))"
    )

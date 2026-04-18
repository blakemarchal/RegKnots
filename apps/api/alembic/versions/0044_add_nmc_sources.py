"""add nmc_policy and nmc_checklist, drop nmc_memo

Revision ID: 0044
Revises: 0043
Create Date: 2026-04-18

Splits the NMC corpus into two structured sources (policy letters vs.
procedural checklists) and retires 'nmc_memo', which shipped in 0042 but
had zero production rows and no working adapter (the dispatch called
discover_and_download() / get_source_date() methods that never existed).

Also repairs a regression in 0042's downgrade path, which dropped
'ism_supplement' from the CHECK constraint even though the supplement
source was — and still is — in active use. The 0044 downgrade restores
the pre-0044 state (which includes ism_supplement AND nmc_memo) rather
than inheriting 0042's bug.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0044"
down_revision: Union[str, None] = "0043"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_memo', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )

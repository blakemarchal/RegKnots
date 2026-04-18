"""add uscg_bulletin source + freshness columns

Revision ID: 0045
Revises: 0044
Create Date: 2026-04-18

Adds a new 'uscg_bulletin' source for USCG GovDelivery bulletin content
(MSIBs, NMC announcements, ALCOAST mentions, policy letter announcements).

Also introduces three additive, nullable freshness columns on the
regulations table — only the uscg_bulletin source populates them today,
but the columns are source-agnostic so any future source can opt in
without another migration:

  published_date DATE        — when the document was first published
  expires_date   DATE        — explicit expiration if stated in body
  superseded_by  VARCHAR(200) — canonical ID of any replacing doc

The (source, published_date) composite index supports future
freshness-aware retrieval queries. Existing rows remain unaffected —
all three columns default NULL.

Preserves every source allowed at 0044. Nothing regresses.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "0045"
down_revision: Union[str, None] = "0044"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement', "
        "'uscg_bulletin'))"
    )

    op.execute("ALTER TABLE regulations ADD COLUMN IF NOT EXISTS published_date DATE")
    op.execute("ALTER TABLE regulations ADD COLUMN IF NOT EXISTS expires_date DATE")
    op.execute("ALTER TABLE regulations ADD COLUMN IF NOT EXISTS superseded_by VARCHAR(200)")

    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_regulations_source_published "
        "ON regulations (source, published_date) "
        "WHERE published_date IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_regulations_source_published")
    op.execute("ALTER TABLE regulations DROP COLUMN IF EXISTS superseded_by")
    op.execute("ALTER TABLE regulations DROP COLUMN IF EXISTS expires_date")
    op.execute("ALTER TABLE regulations DROP COLUMN IF EXISTS published_date")

    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'ism', "
        "'ism_supplement', 'nmc_checklist', 'nmc_policy', 'nvic', "
        "'solas', 'solas_supplement', 'stcw', 'stcw_supplement'))"
    )

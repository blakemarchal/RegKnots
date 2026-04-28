"""add liscr_mn + iri_mn sources

Revision ID: 0060
Revises: 0059
Create Date: 2026-04-28

Sprint D6.20 — adds the two largest open-registry flag-state corpora
to RegKnots. Marine Notices from each registry serve as the flag's
implementation guidance for IMO conventions.

  liscr_mn — Liberian International Ship and Corporate Registry
             Marine Notices. Liberia is the world's #1 open registry
             by gross tonnage.
  iri_mn   — Republic of the Marshall Islands / IRI Marine Notices.
             Marshall Islands is a top-3 open registry.

Both are standard-copyright; ingestion is under fair-use of public
regulatory information for a private RAG knowledge-base, with
attribution + source-URL rendering on every cited chunk.

Pure additive change to the source check constraint.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('amsa_mo', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'imdg', 'imdg_supplement', 'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'marpol', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('amsa_mo', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'imdg', 'imdg_supplement', 'ism', 'ism_supplement', "
        "'marpol', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )

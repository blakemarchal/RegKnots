"""add iacs_pr source code

Revision ID: 0069
Revises: 0068
Create Date: 2026-05-01

Sprint D6.44 — IACS Procedural Requirements as a separate source from
existing iacs_ur (Unified Requirements). PRs cover IACS class-society
internal procedures (class entry, transfer, surveys, audits, casualty
investigation) — different audience and use case from URs which cover
technical requirements that ships must meet.

Pure additive change to regulations.source check constraint.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0069"
down_revision: Union[str, None] = "0068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', "
        "'imo_bwm', 'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
        "'imo_igf', 'imo_loadlines', 'imo_polar', "
        "'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_amend', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'iacs_ur', 'imdg', 'imdg_supplement', "
        "'imo_bwm', 'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
        "'imo_igf', 'imo_loadlines', 'imo_polar', "
        "'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_amend', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )

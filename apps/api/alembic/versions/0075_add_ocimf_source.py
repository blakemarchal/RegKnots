"""add ocimf source code

Revision ID: 0075
Revises: 0074
Create Date: 2026-05-02

Sprint D6.50 — OCIMF public layer (SIRE 2.0 + Information Papers +
operational guidance). Member-only content (full SIRE 2.0 question
library beyond Part 1, ISGOTT 6th, MEG-4, etc.) is intentionally NOT
ingested — those require OCIMF membership.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0075"
down_revision: Union[str, None] = "0074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bg_verkehr', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', "
        "'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
        "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', "
        "'imo_bwm', 'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
        "'imo_igf', 'imo_loadlines', 'imo_polar', "
        "'iri_mn', 'ism', 'ism_supplement', 'it_capitaneria', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'ocimf', "
        "'solas', 'solas_supplement', "
        "'stcw', 'stcw_amend', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bg_verkehr', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', "
        "'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
        "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', "
        "'imo_bwm', 'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
        "'imo_igf', 'imo_loadlines', 'imo_polar', "
        "'iri_mn', 'ism', 'ism_supplement', 'it_capitaneria', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_amend', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )

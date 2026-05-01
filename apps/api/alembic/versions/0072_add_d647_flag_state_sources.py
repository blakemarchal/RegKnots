"""add D6.47 flag-state source codes

Revision ID: 0072
Revises: 0071
Create Date: 2026-05-01

Sprint D6.47 — four new multilingual flag-state regulators:
  bg_verkehr      Germany  (de)
  dgmm_es         Spain    (es)
  it_capitaneria  Italy    (it)
  gr_ynanp        Greece   (el)

All four ride on text-embedding-3-small; cross-lingual cosine similarity
of 0.45-0.70 is sufficient for retrieval (validated on FR pilot D6.46).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0072"
down_revision: Union[str, None] = "0071"
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
        "'erg', 'fr_transport', 'iacs_pr', 'iacs_ur', 'imdg', "
        "'imdg_supplement', "
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

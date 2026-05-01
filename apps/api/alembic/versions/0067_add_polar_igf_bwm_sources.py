"""add imo_polar + imo_igf + imo_bwm source codes

Revision ID: 0067
Revises: 0066
Create Date: 2026-05-01

Sprint D6.41 — three new IMO instrument source codes for the corpus
gap audit identified in D6.36's wrap-up:

  imo_polar — Polar Code (MSC.385/.386 + MEPC.264/.265)
  imo_igf   — IGF Code (MSC.391 + MSC.392)
  imo_bwm   — BWM Convention via implementing MEPC resolutions
              (Convention text itself is paywalled but the operational
              D-1/D-2 standards + BWMS Code + biofouling guidelines
              are all in free MEPC resolutions)

Pure additive change to the regulations.source check constraint.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'iacs_ur', 'imdg', 'imdg_supplement', "
        "'imo_bwm', 'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
        "'imo_igf', 'imo_loadlines', 'imo_polar', "
        "'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
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
        "'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', 'imo_loadlines', "
        "'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )

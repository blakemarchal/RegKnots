"""add fr_transport source code

Revision ID: 0071
Revises: 0070
Create Date: 2026-05-01

Sprint D6.46 — France Code des transports, Partie V (Maritime). First
French-language flag-state pilot validating multilingual ingest on the
existing text-embedding-3-small embedder.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0071"
down_revision: Union[str, None] = "0070"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
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

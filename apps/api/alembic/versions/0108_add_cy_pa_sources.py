"""add 'cy_dms' and 'pa_mmc' to regulations.source check constraint

Revision ID: 0108
Revises: 0107
Create Date: 2026-05-22

Sprint D6.97 flag-state expansion (2026-05-22):
  cy_dms — Cyprus Shipping Deputy Ministry circulars (~178 English-
           named circulars across 2018-2023 archives on gov.cy/dms).
  pa_mmc — Panama Maritime Authority MMCs + MMNs (~100 active
           circulars via the panamashipregistry.com mirror; the
           official amp.gob.pa site is Cloudflare-protected per the
           2026-05-22 recon).

Mirrors the migration pattern of 0104 / 0105 / 0106 / 0107.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0108"
down_revision: Union[str, None] = "0107"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'cy_dms', 'dgmm_es', "
    "'erg', 'fr_transport', 'gr_ynanp', 'iacs_csr', 'iacs_pr', 'iacs_ur', "
    "'imdg', 'imdg_supplement', 'imo_bwm', 'imo_css', 'imo_fss', "
    "'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', 'imo_igf', "
    "'imo_loadlines', 'imo_lsa', 'imo_polar', 'iri_mn', 'ism', "
    "'ism_supplement', 'it_capitaneria', 'liscr_mn', 'lr_lifting_code', "
    "'lr_rules', 'mardep_msin', 'marpol', 'marpol_amend', "
    "'marpol_supplement', 'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', "
    "'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', 'nmc_policy', 'nscv', "
    "'nvic', 'ocimf', 'pa_mmc', 'solas', 'solas_supplement', 'stcw', "
    "'stcw_amend', 'stcw_supplement', 'tc_ssb', 'usc_46', "
    "'uscg_bulletin', 'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'dgmm_es', 'erg', "
    "'fr_transport', 'gr_ynanp', 'iacs_csr', 'iacs_pr', 'iacs_ur', "
    "'imdg', 'imdg_supplement', 'imo_bwm', 'imo_css', 'imo_fss', "
    "'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', 'imo_igf', "
    "'imo_loadlines', 'imo_lsa', 'imo_polar', 'iri_mn', 'ism', "
    "'ism_supplement', 'it_capitaneria', 'liscr_mn', 'lr_lifting_code', "
    "'lr_rules', 'mardep_msin', 'marpol', 'marpol_amend', "
    "'marpol_supplement', 'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', "
    "'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', 'nmc_policy', 'nscv', "
    "'nvic', 'ocimf', 'solas', 'solas_supplement', 'stcw', 'stcw_amend', "
    "'stcw_supplement', 'tc_ssb', 'usc_46', 'uscg_bulletin', "
    "'uscg_msm', 'who_ihr"
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE regulations DROP CONSTRAINT regulations_source_check"
    )
    op.execute(
        f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        f"CHECK (source IN ('{_NEW_SOURCES}'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE regulations DROP CONSTRAINT regulations_source_check"
    )
    op.execute(
        f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        f"CHECK (source IN ('{_OLD_SOURCES}'))"
    )

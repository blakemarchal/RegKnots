"""add 'imo_symbols' to regulations.source check constraint

Revision ID: 0110
Revises: 0109
Create Date: 2026-05-25

Sprint D6.97 #48 (2026-05-25) — IMO graphical-symbol Assembly
resolutions ingest:

  A.952(23)  — Graphical Symbols for Shipboard Fire Control Plans
  A.760(18)  — Symbols Related to Life-Saving Appliances (superseded
               but retained for historical FCPs / pre-2018 LSA marks)
  A.1116(30) — Revised LSA symbols + escape route signs (current)

Same imo_codes.py adapter; new key plugged into _CURATED_BY_CODE and
_CODE_TO_SOURCE. Mirrors the pattern of migrations 0104 / 0105 / 0106.

Motivation: Karynn's 2026-05-23 "Are IMO stickers required for FF
equipment?" query — the engine correctly named A.952(23) and A.760(18)
as the controlling resolutions but had to hedge because neither was
in corpus. With this ingest, the engine can cite them directly.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0110"
down_revision: Union[str, None] = "0109"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'cy_dms', 'dgmm_es', "
    "'erg', 'fr_transport', 'gr_ynanp', 'iacs_csr', 'iacs_pr', "
    "'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', 'imo_css', "
    "'imo_fss', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
    "'imo_igf', 'imo_loadlines', 'imo_lsa', 'imo_polar', 'imo_symbols', "
    "'iri_mn', 'ism', 'ism_supplement', 'it_capitaneria', 'liscr_mn', "
    "'lr_lifting_code', 'lr_rules', 'mardep_msin', 'marpol', "
    "'marpol_amend', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
    "'mou_psc', 'mpa_sc', 'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', "
    "'nmc_policy', 'nscv', 'nvic', 'ocimf', 'pa_mmc', 'solas', "
    "'solas_supplement', 'stcw', 'stcw_amend', 'stcw_supplement', "
    "'tc_ssb', 'usc_46', 'uscg_bulletin', 'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'cy_dms', 'dgmm_es', "
    "'erg', 'fr_transport', 'gr_ynanp', 'iacs_csr', 'iacs_pr', "
    "'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', 'imo_css', "
    "'imo_fss', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
    "'imo_igf', 'imo_loadlines', 'imo_lsa', 'imo_polar', "
    "'iri_mn', 'ism', 'ism_supplement', 'it_capitaneria', 'liscr_mn', "
    "'lr_lifting_code', 'lr_rules', 'mardep_msin', 'marpol', "
    "'marpol_amend', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
    "'mou_psc', 'mpa_sc', 'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', "
    "'nmc_policy', 'nscv', 'nvic', 'ocimf', 'pa_mmc', 'solas', "
    "'solas_supplement', 'stcw', 'stcw_amend', 'stcw_supplement', "
    "'tc_ssb', 'usc_46', 'uscg_bulletin', 'uscg_msm', 'who_ihr"
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

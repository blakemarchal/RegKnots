"""add 'imo_lsa' and 'imo_fss' to regulations.source check constraint

Revision ID: 0106
Revises: 0105
Create Date: 2026-05-21

Sprint D6.97 class-society expansion (2026-05-21) — two IMO codes that
were heavily referenced by SOLAS but missing from corpus until now:

  imo_lsa  — LSA Code (Lifesaving Appliances). MSC.48(66) adoption +
             MSC.485(103) 2021 amendments. Mandatory under SOLAS Ch.III.

  imo_fss  — FSS Code (Fire Safety Systems). MSC.98(73) adoption.
             Mandatory under SOLAS Ch.II-2.

Same imo_codes.py adapter; new keys plugged into _CURATED_BY_CODE and
_CODE_TO_SOURCE. Mirrors the pattern of migrations 0104 / 0105.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0106"
down_revision: Union[str, None] = "0105"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
    "abs_mvr', 'amsa_mo', 'bg_verkehr', 'bma_mn', 'bv', 'cfr_33', 'cfr_46', "
    "'cfr_49', 'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
    "'iacs_csr', 'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', "
    "'imo_bwm', 'imo_css', 'imo_fss', 'imo_hsc', 'imo_iamsar', 'imo_ibc', "
    "'imo_igc', 'imo_igf', 'imo_loadlines', 'imo_lsa', 'imo_polar', "
    "'iri_mn', 'ism', 'ism_supplement', 'it_capitaneria', 'liscr_mn', "
    "'lr_lifting_code', 'lr_rules', 'mardep_msin', 'marpol', "
    "'marpol_amend', 'marpol_supplement', 'mca_mgn', 'mca_msn', 'mou_psc', "
    "'mpa_sc', 'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', 'nmc_policy', "
    "'nscv', 'nvic', 'ocimf', 'solas', 'solas_supplement', 'stcw', "
    "'stcw_amend', 'stcw_supplement', 'tc_ssb', 'usc_46', 'uscg_bulletin', "
    "'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
    "abs_mvr', 'amsa_mo', 'bg_verkehr', 'bma_mn', 'bv', 'cfr_33', 'cfr_46', "
    "'cfr_49', 'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
    "'iacs_csr', 'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', "
    "'imo_bwm', 'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', "
    "'imo_igf', 'imo_loadlines', 'imo_polar', 'iri_mn', 'ism', "
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

"""add 'mlc' to regulations.source check constraint

Revision ID: 0114
Revises: 0113
Create Date: 2026-06-06

Sprint D6.97 audit (2026-06) — ILO Maritime Labour Convention 2006
(as amended, incl. 2022). The labour "fourth pillar" of maritime
regulation. Nirmal Chopra's 2026-06-04 provisions question (food and
catering, Reg 3.2 / Standard A3.2) exposed the gap: the corpus held
458 "MLC" sections but all were German (BG Verkehr) and Liberian
(LISCR) *implementations*, never the convention text. New source
'mlc', tagged ['intl'] (binds every ratifying flag, like SOLAS/STCW).

Mirrors the pattern of 0110 / 0111 / 0113.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0114"
down_revision: Union[str, None] = "0113"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'coswp', 'cy_dms', "
    "'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', 'iacs_csr', "
    "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', "
    "'imo_css', 'imo_fss', 'imo_hsc', 'imo_iamsar', 'imo_ibc', "
    "'imo_igc', 'imo_igf', 'imo_loadlines', 'imo_lsa', 'imo_mepc', "
    "'imo_msc', 'imo_polar', 'imo_symbols', 'iri_mn', 'ism', "
    "'ism_supplement', 'it_capitaneria', 'liscr_mn', 'lr_lifting_code', "
    "'lr_rules', 'mardep_msin', 'marpol', 'marpol_amend', "
    "'marpol_supplement', 'mca_mgn', 'mca_msn', 'mlc', 'mou_psc', "
    "'mpa_sc', 'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', "
    "'nmc_policy', 'nscv', 'nvic', 'ocimf', 'pa_mmc', 'solas', "
    "'solas_supplement', 'stcw', 'stcw_amend', 'stcw_supplement', "
    "'tc_ssb', 'usc_46', 'uscg_bulletin', 'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'coswp', 'cy_dms', "
    "'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', 'iacs_csr', "
    "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', "
    "'imo_css', 'imo_fss', 'imo_hsc', 'imo_iamsar', 'imo_ibc', "
    "'imo_igc', 'imo_igf', 'imo_loadlines', 'imo_lsa', 'imo_mepc', "
    "'imo_msc', 'imo_polar', 'imo_symbols', 'iri_mn', 'ism', "
    "'ism_supplement', 'it_capitaneria', 'liscr_mn', 'lr_lifting_code', "
    "'lr_rules', 'mardep_msin', 'marpol', 'marpol_amend', "
    "'marpol_supplement', 'mca_mgn', 'mca_msn', 'mou_psc', "
    "'mpa_sc', 'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', "
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

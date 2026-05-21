"""add nscv to regulations.source check constraint

Revision ID: 0104
Revises: 0103
Create Date: 2026-05-21

Sprint D6.97 AU sprint 1b — Phase 1b's first ingest run hit a
check_constraint violation because 'nscv' wasn't in the allowed list.
This migration drops the existing regulations_source_check, then
re-adds it with 'nscv' included (alphabetically between 'nmc_policy'
and 'nvic' to match the application's PDF_SOURCES list).

Mirrors the pattern of migration 0090 (which added 'nmc_exam_bank').
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0104"
down_revision: Union[str, None] = "0103"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
    "abs_mvr', 'amsa_mo', 'bg_verkehr', 'bma_mn', 'cfr_33', 'cfr_46', "
    "'cfr_49', 'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
    "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', "
    "'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', 'imo_igf', "
    "'imo_loadlines', 'imo_polar', 'iri_mn', 'ism', 'ism_supplement', "
    "'it_capitaneria', 'liscr_mn', 'lr_lifting_code', 'lr_rules', "
    "'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
    "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', 'nmc_checklist', "
    "'nmc_exam_bank', 'nmc_policy', 'nscv', 'nvic', 'ocimf', 'solas', "
    "'solas_supplement', 'stcw', 'stcw_amend', 'stcw_supplement', 'tc_ssb', "
    "'usc_46', 'uscg_bulletin', 'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
    "abs_mvr', 'amsa_mo', 'bg_verkehr', 'bma_mn', 'cfr_33', 'cfr_46', "
    "'cfr_49', 'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
    "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', "
    "'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', 'imo_igf', "
    "'imo_loadlines', 'imo_polar', 'iri_mn', 'ism', 'ism_supplement', "
    "'it_capitaneria', 'liscr_mn', 'lr_lifting_code', 'lr_rules', "
    "'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
    "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', 'nmc_checklist', "
    "'nmc_exam_bank', 'nmc_policy', 'nvic', 'ocimf', 'solas', "
    "'solas_supplement', 'stcw', 'stcw_amend', 'stcw_supplement', 'tc_ssb', "
    "'usc_46', 'uscg_bulletin', 'uscg_msm', 'who_ihr"
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

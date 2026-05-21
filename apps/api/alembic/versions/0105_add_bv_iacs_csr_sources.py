"""add 'bv' and 'iacs_csr' to regulations.source check constraint

Revision ID: 0105
Revises: 0104
Create Date: 2026-05-21

Sprint D6.97 class-society expansion (2026-05-21).

Two new source keys:
  - 'bv'        — Bureau Veritas Rules (NR467 Parts A-F at launch, others
                  to follow). BV-authored content.
  - 'iacs_csr'  — IACS Common Structural Rules for Bulk Carriers and Oil
                  Tankers. BV distributes this as NR606; ABS / DNV /
                  Lloyd's / ClassNK all publish identical text. Tagged
                  with the international authority key rather than the
                  distributing society so users searching for CSR find
                  it under the canonical name.

Mirrors the pattern of migration 0104 (added 'nscv').
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0105"
down_revision: Union[str, None] = "0104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
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

_OLD_SOURCES = (
    "abs_mvr', 'amsa_mo', 'bg_verkehr', 'bma_mn', 'cfr_33', 'cfr_46', "
    "'cfr_49', 'colregs', 'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', "
    "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', "
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

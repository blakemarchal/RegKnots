"""add 'coswp' to regulations.source check constraint

Revision ID: 0111
Revises: 0110
Create Date: 2026-05-27

Sprint D6.97 #54 (2026-05-27) — UK MCA Code of Safe Working Practices
for Merchant Seafarers, 2025 Edition. Provided by Captain Karynn
Marchal as the priority ingest for the shore-side compliance officer
pivot. Crown Copyright, Open Government Licence v3.

New source key: 'coswp'. Tagged with jurisdiction ['uk'] in
jurisdiction.py. The Code is primarily authored for UK-registered
ships, but the UK query-signal pattern also recognizes "COSWP" or
"Code of Safe Working Practices" so non-UK users can invoke it
explicitly.

Mirrors the pattern of migrations 0104 / 0105 / 0106 / 0108 / 0110.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0111"
down_revision: Union[str, None] = "0110"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_SOURCES = (
    "abs_mvr', 'amsa_mo', 'au_statutes', 'bg_verkehr', 'bma_mn', 'bv', "
    "'cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'coswp', 'cy_dms', "
    "'dgmm_es', 'erg', 'fr_transport', 'gr_ynanp', 'iacs_csr', "
    "'iacs_pr', 'iacs_ur', 'imdg', 'imdg_supplement', 'imo_bwm', "
    "'imo_css', 'imo_fss', 'imo_hsc', 'imo_iamsar', 'imo_ibc', "
    "'imo_igc', 'imo_igf', 'imo_loadlines', 'imo_lsa', 'imo_polar', "
    "'imo_symbols', 'iri_mn', 'ism', 'ism_supplement', "
    "'it_capitaneria', 'liscr_mn', 'lr_lifting_code', 'lr_rules', "
    "'mardep_msin', 'marpol', 'marpol_amend', 'marpol_supplement', "
    "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
    "'nmc_checklist', 'nmc_exam_bank', 'nmc_policy', 'nscv', 'nvic', "
    "'ocimf', 'pa_mmc', 'solas', 'solas_supplement', 'stcw', "
    "'stcw_amend', 'stcw_supplement', 'tc_ssb', 'usc_46', "
    "'uscg_bulletin', 'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
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

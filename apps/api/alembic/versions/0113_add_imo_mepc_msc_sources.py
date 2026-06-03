"""add 'imo_mepc' and 'imo_msc' to regulations.source check constraint

Revision ID: 0113
Revises: 0112
Create Date: 2026-06-03

Sprint D6.97 #53/#57 (2026-06-03) — IMO numbered-resolution harvest,
Phase 1. Two new sources for curated high-value MEPC + MSC/Assembly
resolutions that the corpus previously only REFERENCED:

  imo_mepc — MEPC pollution resolutions. Anchored by Nirmal Chopra's
             (Maersk) 15 ppm oil-content-monitor UTC question
             2026-06-03: MEPC.107(49) + MEPC.276(70) (bilge alarm
             spec + tamper-proof recording), MEPC.108(49) + 240(65)
             (ODME for tankers), MEPC.259(68)/184(59)/305(73)
             (EGCS / scrubbers). Grouped with 'marpol' for affinity.

  imo_msc  — MSC + Assembly safety/operational resolutions:
             MSC.215(82)/288(87) (PSPC protective coatings),
             MSC.402(96) (LSA maintenance/servicing),
             A.1050(27) (enclosed-space entry), A.1047(27) (safe
             manning). Grouped with 'solas' for affinity.

Same imo_codes.py adapter; new keys mepc_res/msc_res in
_CURATED_BY_CODE + _CODE_TO_SOURCE. Mirrors 0106 / 0110 / 0111.

The MSC.1/Circ + MEPC.1/Circ unified-interpretation circulars are
NOT on the IndexofIMOResolutions CDN (404) and are deferred to a
later phase with separate sourcing.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0113"
down_revision: Union[str, None] = "0112"
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
    "'marpol_supplement', 'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', "
    "'nma_rsv', 'nmc_checklist', 'nmc_exam_bank', 'nmc_policy', 'nscv', "
    "'nvic', 'ocimf', 'pa_mmc', 'solas', 'solas_supplement', 'stcw', "
    "'stcw_amend', 'stcw_supplement', 'tc_ssb', 'usc_46', "
    "'uscg_bulletin', 'uscg_msm', 'who_ihr"
)

_OLD_SOURCES = (
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

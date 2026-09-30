"""add the inland / Coast Guard sources to regulations.source check constraint

Revision ID: 0119
Revises: 0118
Create Date: 2026-09-30

Corpus gap audit for U.S. inland and Coast Guard users
(docs/sprint-audits/corpus-gap-audit-inland-2026-09-29.md §4):

  cfr_29             OSHA maritime standards (29 CFR 1915, 1917, 1918, 1919)
  cfr_40             EPA vessel discharge and engine rules (40 CFR 110, 139, 140, 1042, 1043)
  cfr_47             FCC maritime radio (47 CFR 80)
  cfr_50             NOAA right whale rules (50 CFR 224)
  epa_vgp            EPA 2013 Vessel General Permit
  usc_33             33 USC maritime chapters (OPA 90, CWA 311/312, APPS, VBBRA, Rivers and Harbors)
  uscg_cvc           CG-CVC policy letters, work instructions and forms
  uscg_safety_alert  USCG Safety Alerts (CG-INV)
  uscg_towing        TVNCOE Subchapter M FAQs and guides
  uscg_waterways     VTS user manuals and Eighth District Waterways Action Plans

The live constraint was read before writing this (2026-09-30): it matched
0114's list exactly, so no source added by direct SQL is lost by the swap.
Mirrors the pattern of 0110 / 0111 / 0113 / 0114.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0119"
down_revision: Union[str, None] = "0118"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD = [
    "abs_mvr", "amsa_mo", "au_statutes", "bg_verkehr", "bma_mn", "bv",
    "cfr_33", "cfr_46", "cfr_49", "colregs", "coswp", "cy_dms",
    "dgmm_es", "erg", "fr_transport", "gr_ynanp", "iacs_csr",
    "iacs_pr", "iacs_ur", "imdg", "imdg_supplement", "imo_bwm",
    "imo_css", "imo_fss", "imo_hsc", "imo_iamsar", "imo_ibc",
    "imo_igc", "imo_igf", "imo_loadlines", "imo_lsa", "imo_mepc",
    "imo_msc", "imo_polar", "imo_symbols", "iri_mn", "ism",
    "ism_supplement", "it_capitaneria", "liscr_mn", "lr_lifting_code",
    "lr_rules", "mardep_msin", "marpol", "marpol_amend",
    "marpol_supplement", "mca_mgn", "mca_msn", "mlc", "mou_psc",
    "mpa_sc", "nma_rsv", "nmc_checklist", "nmc_exam_bank",
    "nmc_policy", "nscv", "nvic", "ocimf", "pa_mmc", "solas",
    "solas_supplement", "stcw", "stcw_amend", "stcw_supplement",
    "tc_ssb", "usc_46", "uscg_bulletin", "uscg_msm", "who_ihr",
]
_ADDED = [
    "cfr_29", "cfr_40", "cfr_47", "cfr_50", "epa_vgp", "usc_33",
    "uscg_cvc", "uscg_safety_alert", "uscg_towing", "uscg_waterways",
]


def _check(sources: list[str]) -> str:
    listed = ", ".join(f"'{s}'" for s in sorted(sources))
    return f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check CHECK (source IN ({listed}))"


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT regulations_source_check")
    op.execute(_check(_OLD + _ADDED))


def downgrade() -> None:
    op.execute(f"DELETE FROM regulations WHERE source IN ({', '.join(repr(s) for s in _ADDED)})")
    op.execute("ALTER TABLE regulations DROP CONSTRAINT regulations_source_check")
    op.execute(_check(_OLD))

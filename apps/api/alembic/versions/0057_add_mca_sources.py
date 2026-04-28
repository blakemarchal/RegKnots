"""add mca_mgn + mca_msn sources

Revision ID: 0057
Revises: 0056
Create Date: 2026-04-28

Sprint D6.18 — first non-US national-flag corpus. UK Maritime and
Coastguard Agency notices, in two distinct sources for tier and
storage reasons:

  mca_mgn — Marine Guidance Notes (Tier 2: authoritative MCA
    interpretation, parallels US NVIC). M/F/M+F suffix indicates
    applicability scope (merchant / fishing / both).

  mca_msn — Merchant Shipping Notices (Tier 1: technical detail of
    statutory instruments; binding requirements paired with the
    Merchant Shipping Act 1995 + relevant SIs). Often the substantive
    detail behind regulations like SI 2020/646.

Both published under the Open Government Licence v3.0; commercial
use, paraphrasing, and short quotes are explicitly permitted with
attribution. Same legal posture as our CFR ingest.

Pure additive change to the source check constraint.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'imdg', "
        "'imdg_supplement', 'ism', 'ism_supplement', 'marpol', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ('cfr_33', 'cfr_46', 'cfr_49', 'colregs', 'erg', 'imdg', "
        "'imdg_supplement', 'ism', 'ism_supplement', 'marpol', 'marpol_supplement', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', 'stcw', "
        "'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'))"
    )

"""add Norway NMA + Tier D international reference sources

Revision ID: 0063
Revises: 0062
Create Date: 2026-04-28

Sprint D6.23 — adds:

  Norway flag-state:
    nma_rsv      — Norwegian Maritime Authority (Sjøfartsdirektoratet)
                   circulars (RSR / RSV / SM series). English-language;
                   no translation pipeline needed for Norway.

  IACS class society:
    iacs_ur      — IACS Unified Requirements (UR series across A, B, E,
                   F, M, S, W, Z domains). Tier 4 (technical reference
                   standard, like ERG).

  IMO instrument codes (Tier 1 — peer with SOLAS):
    imo_css      — Code of Safe Practice for Cargo Stowage and Securing
    imo_loadlines — International Convention on Load Lines (1966 + 1988)
    imo_igc      — International Gas Carrier Code
    imo_ibc      — International Bulk Chemicals Code
    imo_hsc      — High-Speed Craft Code (2000)

  IMO reference manual (Tier 4):
    imo_iamsar   — IAMSAR Manual Vol III (Mobile Facilities)

  Port State Control (Tier 3, time-sensitive operational notice):
    mou_psc      — Tokyo MOU + Paris MOU annual reports, CIC reports,
                   and deficiency code reference lists.

Pure additive change.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0063"
down_revision: Union[str, None] = "0062"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'iacs_ur', 'imdg', 'imdg_supplement', "
        "'imo_css', 'imo_hsc', 'imo_iamsar', 'imo_ibc', 'imo_igc', 'imo_loadlines', "
        "'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mou_psc', 'mpa_sc', 'nma_rsv', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'bma_mn', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'imdg', 'imdg_supplement', 'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'mardep_msin', 'marpol', 'marpol_supplement', "
        "'mca_mgn', 'mca_msn', 'mpa_sc', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'tc_ssb', 'uscg_bulletin', "
        "'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )

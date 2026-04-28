"""add Singapore + HK + Canada + Bahamas flag-state sources

Revision ID: 0062
Revises: 0061
Create Date: 2026-04-28

Sprint D6.22 — fourth wave of national-flag corpus expansion. Brings
total flag coverage to:

  US, UK, AU, LR, MH, SG, HK, CA, BS  (9 flags)

  + IMO conventions (SOLAS, COLREGs, STCW, ISM, MARPOL, IMDG, ERG, WHO IHR)

  mpa_sc      — Singapore MPA Shipping Circulars + Port Marine Circulars.
                Standard copyright; fair-use ingest. Tier 1 for SG-flag.
  mardep_msin — Hong Kong Marine Department Merchant Shipping Information
                Notes (MSINs). HKSAR govt copyright; fair-use. Tier 1.
  tc_ssb      — Transport Canada Ship Safety Bulletins. Open Government
                Licence – Canada (commercial use OK with attribution).
                Tier 2 — bulletins are advisory; binding regs live in CSA
                and Marine Personnel Regulations (not in this corpus yet).
  bma_mn      — Bahamas Maritime Authority Marine Notices. Standard
                copyright; fair-use posture. Tier 2 — guidance form.

Pure additive change. NZ + Malta deferred — both blocked by anti-bot
on direct-fetch and need a browser-automation pass before ingest.

Note 0061 was claimed earlier in this branch but never landed (the
column it was meant to add already existed). This is the next live
migration after 0060.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0062"
down_revision: Union[str, None] = "0060"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
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


def downgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    op.execute(
        "ALTER TABLE regulations ADD CONSTRAINT regulations_source_check "
        "CHECK (source IN ("
        "'amsa_mo', 'cfr_33', 'cfr_46', 'cfr_49', 'colregs', "
        "'erg', 'imdg', 'imdg_supplement', 'iri_mn', 'ism', 'ism_supplement', "
        "'liscr_mn', 'marpol', 'marpol_supplement', 'mca_mgn', 'mca_msn', "
        "'nmc_checklist', 'nmc_policy', 'nvic', 'solas', 'solas_supplement', "
        "'stcw', 'stcw_supplement', 'uscg_bulletin', 'usc_46', 'who_ihr', 'uscg_msm'"
        "))"
    )

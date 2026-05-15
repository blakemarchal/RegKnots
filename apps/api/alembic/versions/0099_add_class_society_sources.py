"""add lr_rules, lr_lifting_code, abs_mvr to regulations source allowlist

Revision ID: 0099
Revises: 0098
Create Date: 2026-05-15

Sprint D6.93 — first class-society corpus expansion.

Adds three new source tags to the regulations.source CHECK constraint:

  * lr_lifting_code — Lloyd's Register Code for Lifting Appliances in
    a Marine Environment (LR-CO-001). 15 .docx files from Regs4ships;
    one Section per (chapter, section) pair. Covers cranes, derricks,
    ro-ro access, lifts, shiplifts, cargo gear, materials, testing,
    survey requirements. Citation shape: "LR-CO-001 Ch.10 Sec.2".

  * lr_rules — Lloyd's Register Rules and Regulations for the
    Classification of Ships (LR-RU-001). The big one — hull
    construction, machinery, electrical engineering, surveys, periodic
    inspection, ship-type-specific rules. This is the document
    Karynn's 2026-05-13 transformer-failure question needs (Pt 6
    Electrical Engineering for the failure mode + Pt 1 Surveys for
    the reporting trigger). Citation shape: "LR-RU-001 Ch.X Sec.Y".

  * abs_mvr — ABS Marine Vessel Rules (consolidated PDFs from
    ww2.eagle.org). ABS classes ~70% of U.S.-flag commercial vessels;
    the MVR is the consolidated rule set covering hull, machinery,
    electrical, surveys, ship-type-specific requirements. We have
    Parts 3, 4, 5C-1, 5C-2, 5D, 6 plus Notices and the Class
    Notations table (217 MB total). Parts 1/2/5A/5B/7 use a filename
    pattern outside the discoverable set and are deferred. Citation
    shape: "ABS MVR Pt.4 Ch.2 Sec.1".

Follows the canonical drop+recreate pattern from migrations 0090,
0067, 0057 — full live constraint definition (queried from prod
2026-05-15 via pg_get_constraintdef) plus the three new values.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0099"
down_revision: Union[str, None] = "0098"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sources currently live on prod (queried 2026-05-15 via
# pg_get_constraintdef on regulations_source_check). 52 entries —
# matches migration 0090's _SOURCES exactly, no live-only sources
# have been added since.
#
# Plus three new class-society sources for D6.93.
_SOURCES = [
    "abs_mvr",  # D6.93 — ABS Marine Vessel Rules
    "amsa_mo", "bg_verkehr", "bma_mn", "cfr_33", "cfr_46", "cfr_49",
    "colregs", "dgmm_es", "erg", "fr_transport", "gr_ynanp",
    "iacs_pr", "iacs_ur", "imdg", "imdg_supplement",
    "imo_bwm", "imo_css", "imo_hsc", "imo_iamsar", "imo_ibc", "imo_igc",
    "imo_igf", "imo_loadlines", "imo_polar",
    "iri_mn", "ism", "ism_supplement", "it_capitaneria", "liscr_mn",
    "lr_lifting_code",  # D6.93 — Lloyd's LR-CO-001
    "lr_rules",         # D6.93 — Lloyd's LR-RU-001
    "mardep_msin", "marpol", "marpol_amend", "marpol_supplement",
    "mca_mgn", "mca_msn", "mou_psc", "mpa_sc", "nma_rsv",
    "nmc_checklist", "nmc_exam_bank", "nmc_policy",
    "nvic", "ocimf", "solas", "solas_supplement", "stcw", "stcw_amend",
    "stcw_supplement", "tc_ssb", "uscg_bulletin", "usc_46", "who_ihr",
    "uscg_msm",
]


def upgrade() -> None:
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    sources_sql = ", ".join(f"'{s}'" for s in _SOURCES)
    op.execute(
        f"ALTER TABLE regulations "
        f"ADD CONSTRAINT regulations_source_check "
        f"CHECK (source = ANY (ARRAY[{sources_sql}]::text[]))"
    )


def downgrade() -> None:
    # Re-tighten the constraint without the three new sources. If any
    # rows were ingested under these sources, the recreate would fail —
    # drop them first if you actually need to roll back:
    #   DELETE FROM regulations WHERE source IN
    #     ('abs_mvr', 'lr_lifting_code', 'lr_rules');
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    new_sources = {"abs_mvr", "lr_lifting_code", "lr_rules"}
    sources_without_new = [s for s in _SOURCES if s not in new_sources]
    sources_sql = ", ".join(f"'{s}'" for s in sources_without_new)
    op.execute(
        f"ALTER TABLE regulations "
        f"ADD CONSTRAINT regulations_source_check "
        f"CHECK (source = ANY (ARRAY[{sources_sql}]::text[]))"
    )

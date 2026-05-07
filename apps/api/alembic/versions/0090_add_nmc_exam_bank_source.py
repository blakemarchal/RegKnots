"""add nmc_exam_bank to regulations source allowlist

Revision ID: 0090
Revises: 0089
Create Date: 2026-05-07

D6.83 Sprint A1 — adds 'nmc_exam_bank' to the regulations.source
CHECK constraint so the curated USCG exam-pool PDFs (q###_*.pdf) can
be ingested.

This source is intentionally NOT in packages/rag/rag/retriever.py's
SOURCE_GROUPS, so chat retrieval ignores it. Only the Study Tools
retrieval path queries it explicitly via WHERE source = 'nmc_exam_bank'.
That preserves chat answer quality (these are practice questions, not
authoritative regulation text) while making the corpus available to
the quiz/study-guide generators.

Note: this migration follows the canonical pattern of dropping +
re-adding the CHECK constraint with the expanded allowlist. We mirror
the live constraint definition (queried from prod 2026-05-07) plus
the new value, so any source already in production stays valid after
the swap.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0090"
down_revision: Union[str, None] = "0089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Sources currently live on prod (queried 2026-05-07 via pg_get_constraintdef).
# Plus the new 'nmc_exam_bank' value. Any source added by direct SQL on
# the VPS (per the project's deployment memory) and not in this list
# would be dropped by the swap — verify against live before running.
_SOURCES = [
    "amsa_mo", "bg_verkehr", "bma_mn", "cfr_33", "cfr_46", "cfr_49",
    "colregs", "dgmm_es", "erg", "fr_transport", "gr_ynanp",
    "iacs_pr", "iacs_ur", "imdg", "imdg_supplement",
    "imo_bwm", "imo_css", "imo_hsc", "imo_iamsar", "imo_ibc", "imo_igc",
    "imo_igf", "imo_loadlines", "imo_polar",
    "iri_mn", "ism", "ism_supplement", "it_capitaneria", "liscr_mn",
    "mardep_msin", "marpol", "marpol_amend", "marpol_supplement",
    "mca_mgn", "mca_msn", "mou_psc", "mpa_sc", "nma_rsv",
    "nmc_checklist", "nmc_policy",
    # Sprint D6.83 — new source for USCG exam-pool questions
    "nmc_exam_bank",
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
    # Re-tighten the constraint without nmc_exam_bank. If any rows were
    # ingested under the new source, this would fail — drop them first
    # if you actually need to roll back.
    op.execute("ALTER TABLE regulations DROP CONSTRAINT IF EXISTS regulations_source_check")
    sources_without_new = [s for s in _SOURCES if s != "nmc_exam_bank"]
    sources_sql = ", ".join(f"'{s}'" for s in sources_without_new)
    op.execute(
        f"ALTER TABLE regulations "
        f"ADD CONSTRAINT regulations_source_check "
        f"CHECK (source = ANY (ARRAY[{sources_sql}]::text[]))"
    )

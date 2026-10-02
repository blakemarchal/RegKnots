"""free exam practice, the free plan's monthly counter, NGA publications source

Revision ID: 0120
Revises: 0119
Create Date: 2026-10-02

1. exam_questions: the NMC sample-examination questions, one row per question
   (packages/ingest/ingest/exam_questions.py), served by the public /practice
   page. needs_figure rows are kept but not served.
2. practice_quiz_starts: one row per quiz started on /practice (the topic only;
   no user, no IP), to measure the page.
3. free_plan_usage: free-plan answers per calendar month, the global cap on the
   free plan (apps/api/app/free_plan.py).
4. regulations_source_check gains nga_pubs (Bowditch, Pub 1310, Pub 102).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0120"
down_revision: Union[str, None] = "0119"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD = [
    "abs_mvr", "amsa_mo", "au_statutes", "bg_verkehr", "bma_mn", "bv",
    "cfr_29", "cfr_33", "cfr_40", "cfr_46", "cfr_47", "cfr_49", "cfr_50",
    "colregs", "coswp", "cy_dms", "dgmm_es", "epa_vgp", "erg",
    "fr_transport", "gr_ynanp", "iacs_csr", "iacs_pr", "iacs_ur", "imdg",
    "imdg_supplement", "imo_bwm", "imo_css", "imo_fss", "imo_hsc",
    "imo_iamsar", "imo_ibc", "imo_igc", "imo_igf", "imo_loadlines",
    "imo_lsa", "imo_mepc", "imo_msc", "imo_polar", "imo_symbols", "iri_mn",
    "ism", "ism_supplement", "it_capitaneria", "liscr_mn",
    "lr_lifting_code", "lr_rules", "mardep_msin", "marpol", "marpol_amend",
    "marpol_supplement", "mca_mgn", "mca_msn", "mlc", "mou_psc", "mpa_sc",
    "nma_rsv", "nmc_checklist", "nmc_exam_bank", "nmc_policy", "nscv",
    "nvic", "ocimf", "pa_mmc", "solas", "solas_supplement", "stcw",
    "stcw_amend", "stcw_supplement", "tc_ssb", "usc_33", "usc_46",
    "uscg_bulletin", "uscg_cvc", "uscg_msm", "uscg_safety_alert",
    "uscg_towing", "uscg_waterways", "who_ihr",
]
_ADDED = ["nga_pubs"]


def _check(sources: list[str]) -> str:
    listed = ", ".join(f"'{s}'" for s in sorted(sources))
    return f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check CHECK (source IN ({listed}))"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE exam_questions (
            id                 serial PRIMARY KEY,
            source_file        text NOT NULL,
            number             integer NOT NULL,
            pool               text NOT NULL,
            part               text NOT NULL DEFAULT '',
            exam               text NOT NULL DEFAULT '',
            topic_key          text NOT NULL,
            topic_label        text NOT NULL,
            stem               text NOT NULL,
            choices            jsonb NOT NULL,
            answer             text NOT NULL,
            needs_figure       boolean NOT NULL DEFAULT false,
            related_source     text,
            related_section    text,
            related_title      text,
            related_similarity real,
            updated_at         timestamptz NOT NULL DEFAULT now(),
            UNIQUE (source_file, number)
        )
    """)
    op.execute("CREATE INDEX ix_exam_questions_topic ON exam_questions (topic_key) WHERE NOT needs_figure")
    op.execute("""
        CREATE TABLE practice_quiz_starts (
            id         bigserial PRIMARY KEY,
            topic_key  text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX ix_practice_quiz_starts_created ON practice_quiz_starts (created_at)")
    op.execute("""
        CREATE TABLE free_plan_usage (
            month   date PRIMARY KEY,
            answers integer NOT NULL DEFAULT 0
        )
    """)
    op.execute("ALTER TABLE regulations DROP CONSTRAINT regulations_source_check")
    op.execute(_check(_OLD + _ADDED))


def downgrade() -> None:
    op.execute(f"DELETE FROM regulations WHERE source IN ({', '.join(repr(s) for s in _ADDED)})")
    op.execute("ALTER TABLE regulations DROP CONSTRAINT regulations_source_check")
    op.execute(_check(_OLD))
    op.execute("DROP TABLE free_plan_usage")
    op.execute("DROP TABLE practice_quiz_starts")
    op.execute("DROP TABLE exam_questions")

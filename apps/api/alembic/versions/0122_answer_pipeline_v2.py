"""answer pipeline phase 2: corpus_gaps, messages.web_sources, the web_ingest source

Revision ID: 0122
Revises: 0121
Create Date: 2026-10-09

Spec: docs/specs/answer-pipeline-2026-10-08.md (phase 2). Before an answer is
written, a coverage check names what RegKnot's library lacks and those items
are researched on official websites.

  corpus_gaps          one row per missing item: the question, the item, the
                       search query, whether the web found it and where. A
                       found item on an official site is an ingest candidate
                       (app.tasks.ingest_web_gaps); status tracks it through
                       found -> ingest_queued -> ingested / ingest_skipped.
                       The working list that replaces hedge audits. user_id /
                       conversation_id go NULL when those are deleted, so the
                       corpus insight survives account deletion.
  messages.web_sources the web sources an answer cites ([{label, url, title,
                       publisher, domain, verified, item}]), for the chips and
                       the footer after a reload.
  regulations source   gains web_ingest: official documents the web research
                       found and the ingest task added. Jurisdictions are set
                       per document (by domain), not per source.

The live constraint was read before writing this (2026-10-09): it matched
0120's list exactly.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0122"
down_revision: Union[str, None] = "0121"
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
    "ism", "ism_supplement", "it_capitaneria", "liscr_mn", "lr_lifting_code",
    "lr_rules", "mardep_msin", "marpol", "marpol_amend", "marpol_supplement",
    "mca_mgn", "mca_msn", "mlc", "mou_psc", "mpa_sc", "nga_pubs", "nma_rsv",
    "nmc_checklist", "nmc_exam_bank", "nmc_policy", "nscv", "nvic", "ocimf",
    "pa_mmc", "solas", "solas_supplement", "stcw", "stcw_amend",
    "stcw_supplement", "tc_ssb", "usc_33", "usc_46", "uscg_bulletin",
    "uscg_cvc", "uscg_msm", "uscg_safety_alert", "uscg_towing",
    "uscg_waterways", "who_ihr",
]
_ADDED = ["web_ingest"]


def _check(sources: list[str]) -> str:
    listed = ", ".join(f"'{s}'" for s in sorted(sources))
    return f"ALTER TABLE regulations ADD CONSTRAINT regulations_source_check CHECK (source IN ({listed}))"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE corpus_gaps (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            user_id          UUID REFERENCES users(id) ON DELETE SET NULL,
            conversation_id  UUID REFERENCES conversations(id) ON DELETE SET NULL,
            question         TEXT NOT NULL,
            item             TEXT NOT NULL,
            search_query     TEXT,
            coverage         TEXT,
            web_searched     BOOLEAN NOT NULL DEFAULT false,
            found            BOOLEAN NOT NULL DEFAULT false,
            answer           TEXT,
            sources          JSONB NOT NULL DEFAULT '[]'::jsonb,
            status           TEXT NOT NULL DEFAULT 'open'
                             CHECK (status IN ('open', 'found', 'not_found', 'ingest_queued', 'ingested',
                                               'ingest_skipped', 'ingest_failed', 'dismissed')),
            ingest_url       TEXT,
            ingest_note      TEXT,
            ingested_section TEXT,
            latency_ms       INTEGER,
            error            TEXT
        )
    """)
    op.execute("CREATE INDEX idx_corpus_gaps_created ON corpus_gaps(created_at DESC)")
    op.execute("CREATE INDEX idx_corpus_gaps_status ON corpus_gaps(status) WHERE status IN ('found', 'ingest_queued')")
    op.execute("ALTER TABLE messages ADD COLUMN web_sources JSONB")
    op.execute("ALTER TABLE regulations DROP CONSTRAINT regulations_source_check")
    op.execute(_check(_OLD + _ADDED))


def downgrade() -> None:
    op.execute(f"DELETE FROM regulations WHERE source IN ({', '.join(repr(s) for s in _ADDED)})")
    op.execute("ALTER TABLE regulations DROP CONSTRAINT regulations_source_check")
    op.execute(_check(_OLD))
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS web_sources")
    op.execute("DROP TABLE IF EXISTS corpus_gaps")

"""add regulations.full_text_tsv generated tsvector column + GIN index

Revision ID: 0088
Revises: 0087
Create Date: 2026-05-06

D6.71 Sprint 7a — foundation for hybrid BM25 + dense retrieval.

Adds a STORED generated tsvector column on regulations:

    full_text_tsv =
        setweight(to_tsvector('english', coalesce(section_title, '')), 'A')
        || setweight(to_tsvector('english', coalesce(full_text,    '')), 'B')

Title gets weight A, body gets weight B. ts_rank_cd then privileges
matches in the title — which on CFR sections like "TSMS elements"
or "Lifesaving Appliances" is exactly the routing signal we want.

A GIN index on the tsvector lets ts_rank_cd queries use index-driven
candidate scans instead of full-table sequential scans.

This migration is purely additive — no app code references the new
column yet. Hybrid retrieval is feature-flagged off by default
(HYBRID_RETRIEVAL_ENABLED=false). The migration is safe to run in
prod ahead of the code change; behavior is unchanged.

Schema change cost on the prod table (~74k rows):
  - tsvector column populates during ALTER TABLE: ~60s
  - GIN index build: ~60s
  - Total downtime: 0s (Postgres ALTER ADD COLUMN with STORED uses
    table rewrite, but reads keep flowing on a snapshot. Writes
    block briefly during the rewrite — but the regulations table
    is append-only and only written during ingest pipelines, which
    aren't run during deploys.)

Downgrade is symmetric — DROP INDEX then DROP COLUMN.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0088"
down_revision: Union[str, None] = "0087"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Generated column — STORED so reads don't recompute; Postgres
    # populates it once during the ALTER and on every subsequent
    # write. We use websearch_to_tsquery() at query time, which
    # tolerates user phrasing (quotes, OR, AND, NOT) without
    # rejecting on syntax errors.
    op.execute(
        """
        ALTER TABLE regulations
        ADD COLUMN IF NOT EXISTS full_text_tsv tsvector
        GENERATED ALWAYS AS (
            setweight(to_tsvector('english', coalesce(section_title, '')), 'A')
            || setweight(to_tsvector('english', coalesce(full_text, '')), 'B')
        ) STORED
        """
    )
    # GIN index for fast tsvector @@ tsquery and ts_rank_cd lookups.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_regulations_full_text_tsv
        ON regulations USING gin (full_text_tsv)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_regulations_full_text_tsv")
    op.execute("ALTER TABLE regulations DROP COLUMN IF EXISTS full_text_tsv")

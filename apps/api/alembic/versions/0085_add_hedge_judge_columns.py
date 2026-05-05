"""add hedge_judge columns to retrieval_misses + web_fallback_responses

Revision ID: 0085
Revises: 0084
Create Date: 2026-05-05

D6.60 — replace the regex-only hedge → fallback decision with a Haiku-
backed judge that classifies hedge events into:
  complete_miss     — fire fallback as today
  partial_miss      — fire fallback w/ judge.missing_topic as the query
  precision_callout — suppress fallback (model added meta-honesty on a
                      complete answer)
  false_hedge       — suppress fallback (regex matched idiomatic usage)

The verdict + Haiku's reasoning are persisted to BOTH tables:
  retrieval_misses          — every hedge event (incl. suppressed ones)
  web_fallback_responses    — denormalized copy for fired events so the
                              /admin/web-fallback page can show the
                              verdict next to surface_tier without a
                              cross-table join
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0085"
down_revision: Union[str, None] = "0084"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE retrieval_misses
            ADD COLUMN IF NOT EXISTS judge_verdict VARCHAR(32),
            ADD COLUMN IF NOT EXISTS judge_reasoning TEXT,
            ADD COLUMN IF NOT EXISTS judge_missing_topic TEXT,
            ADD COLUMN IF NOT EXISTS chunks_truncated_for_judge BOOLEAN DEFAULT FALSE
    """)
    op.execute("""
        ALTER TABLE web_fallback_responses
            ADD COLUMN IF NOT EXISTS judge_verdict VARCHAR(32),
            ADD COLUMN IF NOT EXISTS judge_missing_topic TEXT
    """)
    # Index for filtering by verdict on the admin page (small enum
    # cardinality, so a regular btree is fine).
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_retrieval_misses_judge_verdict
            ON retrieval_misses (judge_verdict)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_retrieval_misses_judge_verdict")
    op.execute("""
        ALTER TABLE web_fallback_responses
            DROP COLUMN IF EXISTS judge_verdict,
            DROP COLUMN IF EXISTS judge_missing_topic
    """)
    op.execute("""
        ALTER TABLE retrieval_misses
            DROP COLUMN IF EXISTS judge_verdict,
            DROP COLUMN IF EXISTS judge_reasoning,
            DROP COLUMN IF EXISTS judge_missing_topic,
            DROP COLUMN IF EXISTS chunks_truncated_for_judge
    """)

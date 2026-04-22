"""add retrieval_misses table (Sprint D2-LOG)

Revision ID: 0047
Revises: 0046
Create Date: 2026-04-22

Captures every chat response whose answer contains a hedge phrase (see
packages/rag/rag/hedge.py). Each row records: the user's query, whether
a vessel profile was set, the top chunks retrieved, which of those the
model actually cited, the matched hedge phrase, and model/token metadata.

Purpose: build a real-world dataset of retrieval failures to tune
against, instead of hand-grepping `messages.content` for hedge phrases
after complaints come in. The Sprint D2.1 eval found that Karynn's
"no vessel profile → partial retrieval → hedge" pattern was invisible
to regex-only grading — this table makes it first-class operational data.

Admin-only read path (via apps/api/app/routers/admin.py). Never exposed
to end users. Auto-populated by packages/rag/rag/engine.py on every
chat() call that produces a hedged answer.

Rows are retained indefinitely for trend analysis; if the table grows
unbounded (unlikely given hedge rate), a future migration can add
partitioning by month.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0047"
down_revision: Union[str, None] = "0046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_misses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
            query TEXT NOT NULL,
            vessel_profile_set BOOLEAN NOT NULL,
            vessel_profile JSONB,
            hedge_phrase_matched TEXT NOT NULL,
            model_used TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            retrieved_chunks JSONB NOT NULL,
            cited_regulations JSONB NOT NULL DEFAULT '[]'::jsonb,
            answer_preview TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_retrieval_misses_created_at "
        "ON retrieval_misses (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_retrieval_misses_vessel_set "
        "ON retrieval_misses (vessel_profile_set, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_retrieval_misses_vessel_set")
    op.execute("DROP INDEX IF EXISTS idx_retrieval_misses_created_at")
    op.execute("DROP TABLE IF EXISTS retrieval_misses")

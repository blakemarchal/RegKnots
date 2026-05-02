"""add query_distillations audit table

Revision ID: 0077
Revises: 0076
Create Date: 2026-05-02

Sprint D6.51 — pre-retrieval query distillation. Logs every distillation
attempt for retrospective tuning: are we distilling the right queries?
Are distillations actually improving retrieval? What does Haiku miss?

Same pattern as web_fallback_responses — fire-and-forget audit, never
blocks the chat response.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0077"
down_revision: Union[str, None] = "0076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS query_distillations (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            user_id UUID,
            conversation_id UUID,

            original_query TEXT NOT NULL,
            distilled_query TEXT,           -- NULL when distillation failed

            model VARCHAR(64) NOT NULL,
            latency_ms INTEGER NOT NULL,
            error VARCHAR(255),             -- NULL on success

            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS query_distillations_created_idx "
        "ON query_distillations(created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS query_distillations_user_idx "
        "ON query_distillations(user_id, created_at DESC) "
        "WHERE user_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS query_distillations_error_idx "
        "ON query_distillations(error, created_at DESC) "
        "WHERE error IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS query_distillations")

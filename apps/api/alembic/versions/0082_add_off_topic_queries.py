"""add off_topic_queries — abuse detection for the LLM scope gate

Revision ID: 0082
Revises: 0081
Create Date: 2026-05-04

Sprint D6.58 prelude to Slice 3.

A scope-check Haiku call now classifies every chat query as
on-topic (1-3 maritime complexity) or off-topic (0). Off-topic
queries short-circuit before retrieval / web fallback / Big-3
ensemble fire — saves real money on what would otherwise be a
clean abuse vector ($0.23+ per off-topic query if it cascaded
through the full stack).

This table logs every off-topic event so we can:

  1. Flag users at 10 off-topics/day in the admin UI (potentially
     confused, not necessarily abusive — review before acting).
  2. Auto rate-limit users at 25 off-topics/day (return 429 for
     further off-topic queries the rest of the calendar day; on-topic
     queries continue to work).
  3. Email the Owner when a user hits 25-cap days on 3 separate days
     in any 30-day window — strong abuse signal, manual block decision.

Daily counts are computed from this table on demand; no denormalized
columns on `users`. The `(user_id, created_at DESC)` index keeps the
"how many off-topics today?" query cheap.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0082"
down_revision: Union[str, None] = "0081"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS off_topic_queries (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID
                REFERENCES users(id) ON DELETE SET NULL,
            -- Conversation context (optional). Useful for debugging
            -- whether the off-topic question came mid-thread or out
            -- of nowhere.
            conversation_id UUID,
            -- The query as the user typed it. Capped at 2000 chars
            -- via app-layer trim so long abusive payloads don't
            -- explode the table.
            query TEXT NOT NULL,
            -- Classifier reasoning, optional, for spot-checking that
            -- the gate isn't false-positive on borderline maritime
            -- questions ("how do I tie a bowline" — should pass).
            classifier_reasoning TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    # Primary admin query: "how many off-topics has this user logged
    # today?". Index covers it in O(log n) per user.
    op.execute(
        "CREATE INDEX IF NOT EXISTS off_topic_queries_user_day_idx "
        "ON off_topic_queries (user_id, created_at DESC) "
        "WHERE user_id IS NOT NULL"
    )
    # Newest-first scan for the global admin view.
    op.execute(
        "CREATE INDEX IF NOT EXISTS off_topic_queries_recency_idx "
        "ON off_topic_queries (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS off_topic_queries")

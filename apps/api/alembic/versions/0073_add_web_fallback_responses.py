"""add web_fallback_responses table

Revision ID: 0073
Revises: 0072
Create Date: 2026-05-01

Sprint D6.48 Phase 1 — web search fallback for the hedge ("I have to be
honest…") path. Fallback fires only when retrieval top-1 cosine < 0.5
(true corpus gap, not retrieval miss). Strict gates: domain on trusted
whitelist + verbatim quote present in source + Claude self-rated
confidence ≥ 4. If any gate fails, the original hedge response stands.

This table logs every fallback attempt — surfaced or not — so we can
audit accuracy retroactively and feed the corpus-discovery loop. The
is_calibration flag distinguishes admin replay runs (no real user
exposure) from production traffic.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0073"
down_revision: Union[str, None] = "0072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS web_fallback_responses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            -- Provenance
            user_id UUID,
            chat_message_id UUID,
            is_calibration BOOLEAN NOT NULL DEFAULT FALSE,

            -- Input
            query TEXT NOT NULL,
            web_query_used TEXT,                        -- may differ from query if reformulated
            retrieval_top1_cosine DOUBLE PRECISION,     -- best corpus-hit cosine when fallback fired

            -- Web search outcome
            top_urls TEXT[] NOT NULL DEFAULT '{}',      -- up to 3 URLs returned by search
            confidence INTEGER,                         -- Claude self-rating 1-5
            source_url TEXT,                            -- the URL we anchored the answer on
            source_domain TEXT,                         -- normalized domain (e.g. "imo.org")
            quote_text TEXT,                            -- verbatim quote from the source
            quote_verified BOOLEAN,                     -- did our extractor confirm the quote?

            -- Decision
            surfaced BOOLEAN NOT NULL,
            surface_blocked_reason VARCHAR(64),         -- low_confidence | domain_blocked | quote_unverified | no_results | error

            -- Final output
            answer_text TEXT,                           -- response shown (or would have been)

            -- Feedback
            user_feedback VARCHAR(16),                  -- helpful | not_helpful | inaccurate | NULL
            user_feedback_at TIMESTAMPTZ,
            user_feedback_note TEXT,

            -- Timing
            latency_ms INTEGER,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        );
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_user_id_idx "
        "ON web_fallback_responses(user_id) WHERE user_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_created_at_idx "
        "ON web_fallback_responses(created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_surfaced_idx "
        "ON web_fallback_responses(surfaced)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_calibration_idx "
        "ON web_fallback_responses(is_calibration, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_feedback_idx "
        "ON web_fallback_responses(user_feedback) "
        "WHERE user_feedback IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS web_fallback_responses")

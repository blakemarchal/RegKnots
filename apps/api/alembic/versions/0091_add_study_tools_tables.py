"""add study_generations + study_quiz_sessions tables for Study Tools

Revision ID: 0091
Revises: 0090
Create Date: 2026-05-07

D6.83 Sprint A2 — backend persistence for the Study Tools product.

Two tables:

  study_generations
    Persists every quiz / guide the user generates. content_json
    holds the structured quiz (questions array) or guide (sections
    array). archived_at mirrors the soft-archive pattern used for
    conversations (D6.80) — same UX semantics, same data preservation
    guarantee.

  study_quiz_sessions
    One row per "take-the-quiz" attempt. Tracks per-question answers
    + final score. Lets the user pause + resume, see history, and
    eventually power the school-tier teacher dashboard ("how did
    your students do on Quiz X").

Monthly generation caps are NOT a separate table — they compute
on-the-fly from `count(*) FROM study_generations WHERE user_id = $1
AND created_at >= date_trunc('month', NOW())`. Avoids a separate
counter that can drift out of sync with the underlying rows.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0091"
down_revision: Union[str, None] = "0090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS study_generations (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind            TEXT NOT NULL CHECK (kind IN ('quiz', 'guide')),
            topic           TEXT NOT NULL,
            topic_key       TEXT,
            title           TEXT NOT NULL,
            content_json    JSONB NOT NULL,
            model_used      TEXT NOT NULL,
            input_tokens    INTEGER NOT NULL DEFAULT 0,
            output_tokens   INTEGER NOT NULL DEFAULT 0,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            archived_at     TIMESTAMPTZ NULL
        )
    """)

    # Per-user listing query: WHERE user_id = $1 AND archived_at IS NULL
    # ORDER BY created_at DESC LIMIT 50. Partial index keeps it cheap
    # without bloat from archived rows.
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_study_generations_user_active
        ON study_generations (user_id, created_at DESC)
        WHERE archived_at IS NULL
    """)

    # Cap-check query: SELECT COUNT(*) WHERE user_id = $1 AND created_at >= ...
    # Same partial index helps here. No need for a separate index.

    op.execute("""
        CREATE TABLE IF NOT EXISTS study_quiz_sessions (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id           UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            generation_id     UUID NOT NULL REFERENCES study_generations(id) ON DELETE CASCADE,
            -- answers JSONB shape:
            --   [{"q": 0, "selected": "B", "correct_letter": "C",
            --     "is_correct": false, "answered_at": "2026-..."}, ...]
            answers           JSONB NOT NULL DEFAULT '[]'::jsonb,
            -- 0-100 percent score; null until finished_at is set
            score_pct         NUMERIC(5,2) NULL,
            started_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            finished_at       TIMESTAMPTZ NULL,
            elapsed_seconds   INTEGER NULL
        )
    """)

    # Resume / history queries — typical: SELECT WHERE user_id AND
    # generation_id ORDER BY started_at DESC LIMIT 1
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_study_quiz_sessions_user_generation
        ON study_quiz_sessions (user_id, generation_id, started_at DESC)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_study_quiz_sessions_user_generation")
    op.execute("DROP TABLE IF EXISTS study_quiz_sessions")
    op.execute("DROP INDEX IF EXISTS idx_study_generations_user_active")
    op.execute("DROP TABLE IF EXISTS study_generations")

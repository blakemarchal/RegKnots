"""extend web_fallback_responses for Big-3 ensemble tracking

Revision ID: 0083
Revises: 0082
Create Date: 2026-05-04

Sprint D6.58 Slice 3 — Big-3 ensemble (Claude + GPT + Grok).

The ensemble path reuses web_fallback_responses for logging — same
table, just with new columns that capture which providers fired,
which surface tier the synthesis picked, and how many providers
agreed on the answer.

Three new columns:

  surface_tier
    'verified' | 'reference' | 'consensus' | 'blocked'
    Replaces the implicit binary `surfaced` flag. 'consensus' is the
    new tier from Slice 3 — surfaces when ≥2/3 ensemble providers
    agreed but we couldn't verify a verbatim quote. UI renders this
    distinct from 'verified' so users never confuse cross-LLM
    consensus with citation-verified RegKnots authority.

  is_ensemble
    Boolean. True when the row represents a Big-3 ensemble fire
    (3 providers in parallel + synthesis). False for legacy single-
    LLM Claude-only fallbacks.

  ensemble_providers
    Text array of providers that ACTUALLY returned a usable response.
    Subset of ['claude','gpt','grok']. Empty list means all failed.

  ensemble_agreement_count
    Integer 0-3. How many providers agreed on the best answer per the
    synthesis call. 3 = strongest consensus; 0 = all disagreed or all
    failed.

Cap-counting query for per-tier monthly limits:
  SELECT COUNT(*) FROM web_fallback_responses
  WHERE user_id = $1 AND is_ensemble = TRUE
    AND created_at > NOW() - INTERVAL '30 days'
  → Captain tier capped at 25, Mate at 10, free trial at 3 lifetime.
The supporting index covers it.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0083"
down_revision: Union[str, None] = "0082"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE web_fallback_responses
            ADD COLUMN IF NOT EXISTS surface_tier VARCHAR(16),
            ADD COLUMN IF NOT EXISTS is_ensemble BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN IF NOT EXISTS ensemble_providers TEXT[],
            ADD COLUMN IF NOT EXISTS ensemble_agreement_count INTEGER
    """)
    # Backfill the existing rows: pre-D6.58 surfaced=true rows were all
    # 'verified' tier under the old single-gate model; surfaced=false
    # rows are 'blocked'. Slice 1 ('reference') went out a few hours
    # ago — those are correctly tagged via the application code so the
    # backfill only touches truly-pre-D6.58 rows.
    op.execute("""
        UPDATE web_fallback_responses
        SET surface_tier = CASE
            WHEN surfaced THEN 'verified'
            ELSE 'blocked'
        END
        WHERE surface_tier IS NULL
    """)
    # Cap-counting + admin-filtering by ensemble status
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_ensemble_user_idx "
        "ON web_fallback_responses (user_id, is_ensemble, created_at DESC) "
        "WHERE user_id IS NOT NULL"
    )
    # Surface-tier filter for the admin UI / hedge audit cross-link
    op.execute(
        "CREATE INDEX IF NOT EXISTS web_fallback_tier_idx "
        "ON web_fallback_responses (surface_tier, created_at DESC) "
        "WHERE surface_tier IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS web_fallback_tier_idx")
    op.execute("DROP INDEX IF EXISTS web_fallback_ensemble_user_idx")
    op.execute("""
        ALTER TABLE web_fallback_responses
            DROP COLUMN IF EXISTS ensemble_agreement_count,
            DROP COLUMN IF EXISTS ensemble_providers,
            DROP COLUMN IF EXISTS is_ensemble,
            DROP COLUMN IF EXISTS surface_tier
    """)

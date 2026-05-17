"""create current_events_responses logging table

Revision ID: 0102
Revises: 0101
Create Date: 2026-05-16

Sprint D6.96 — captures every current-events tier fire (and every
intentionally-blocked attempt) so Karynn can audit weekly and we can
audit miscalls from real traffic.

One row per detector trigger that resulted in either:
  - A surfaced 'current_events' block on the user's answer
  - An intentional block (refusal_reason set, no surfacing)

Fields:
  query                  — verbatim user prompt that triggered detection
  markers_matched        — the trigger phrases that fired
                           (e.g. ['strong:what\\'s happening with',
                                  'hot_topic:strait of hormuz'])
  surface_tier           — 'current_events' (surfaced) or 'blocked'
  refusal_reason         — populated when blocked:
                           'policy_advocacy', 'no_fresh_sources',
                           'stale_only', or null when surfaced
  source_urls            — distinct URLs the Anthropic web_search
                           returned that came from the trusted whitelist
  source_domains         — normalized domains parallel to source_urls
  oldest_quote_date      — earliest YYYY-MM-DD across cited sources
                           (NULL if no dates extractable)
  newest_quote_date      — latest YYYY-MM-DD across cited sources
  answer_text            — the appended 'Current Reading' block contents
  latency_ms             — total wall time for the news fallback call
  user_flagged_stale     — flipped true when the user clicks 'Flag as
                           stale' on the chip — drives Karynn's weekly
                           review queue
  user_flag_note         — optional free-text note from the user
                           explaining what was stale
  flagged_at             — timestamp of the flag-as-stale click
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0102"
down_revision: Union[str, None] = "0101"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE current_events_responses (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            chat_message_id uuid REFERENCES messages(id) ON DELETE CASCADE,
            user_id uuid REFERENCES users(id) ON DELETE SET NULL,
            query text NOT NULL,
            markers_matched text[] NOT NULL DEFAULT '{}',
            surface_tier text NOT NULL
                CHECK (surface_tier IN ('current_events', 'blocked')),
            refusal_reason text
                CHECK (refusal_reason IS NULL OR refusal_reason IN (
                    'policy_advocacy', 'no_fresh_sources', 'stale_only',
                    'error', 'feature_flag_off'
                )),
            source_urls text[] NOT NULL DEFAULT '{}',
            source_domains text[] NOT NULL DEFAULT '{}',
            oldest_quote_date date,
            newest_quote_date date,
            answer_text text,
            latency_ms integer NOT NULL DEFAULT 0,
            user_flagged_stale boolean NOT NULL DEFAULT false,
            user_flag_note text,
            flagged_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_current_events_created_at "
        "ON current_events_responses (created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_current_events_flagged "
        "ON current_events_responses (flagged_at DESC) "
        "WHERE user_flagged_stale = true"
    )
    op.execute(
        "CREATE INDEX idx_current_events_message "
        "ON current_events_responses (chat_message_id) "
        "WHERE chat_message_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS current_events_responses")

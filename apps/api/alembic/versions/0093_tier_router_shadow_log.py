"""add tier_router_shadow_log table for Sprint D6.84 confidence tier router

Revision ID: 0093
Revises: 0092
Create Date: 2026-05-09

D6.84 Sprint A — additive confidence tier router (off / shadow / live).

When CONFIDENCE_TIERS_MODE != "off", every chat response that goes
through the new router writes one row to this table:

  - In "shadow": the user sees today's behavior; this table records
    what the tier router WOULD have rendered. Admin compares both
    side-by-side via /admin/chats/{id}/shadow-comparison.
  - In "live":  the user sees the tier-routed answer; this table
    records the pre-tier "what current setup would have shown" for
    forensics and rollback diagnosis.

The table is forensic — never read on the user-facing chat path.
A row failing to insert MUST NOT block a chat response (the engine
wraps the insert in try/except).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0093"
down_revision: Union[str, None] = "0092"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-message tier metadata so a live-mode answer's chip survives
    # a conversation reload. Nullable — pre-D6.84 messages stay NULL
    # and the frontend renders today's UX for them. Stored as JSONB
    # because the shape is stable but small and we want flexible
    # filtering ("show me all tier=2 messages from this user").
    op.add_column(
        "messages",
        sa.Column(
            "tier_metadata",
            sa.dialects.postgresql.JSONB(),
            nullable=True,
        ),
    )

    op.create_table(
        "tier_router_shadow_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),

        # Linkage. Conversation FK uses ON DELETE CASCADE so admin
        # GDPR / chat-deletion flows clean these up automatically.
        sa.Column(
            "conversation_id", sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        # The assistant message_id this shadow row corresponds to.
        # Nullable because messages can be inserted async / via
        # different paths; we don't want a missing FK to silently
        # drop forensic data.
        sa.Column("message_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True, index=True),
        sa.Column(
            "user_id", sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),

        # The user's query.
        sa.Column("query", sa.Text(), nullable=False),

        # Mode at the time of this row — 'shadow' or 'live'. Lets us
        # later filter the table by deployment phase without joining
        # to release notes.
        sa.Column("mode", sa.String(16), nullable=False),

        # Today's pipeline output (what was/would be rendered without
        # the tier router).
        sa.Column("current_answer", sa.Text(), nullable=False),
        sa.Column("current_judge_verdict", sa.String(32), nullable=True),
        sa.Column("current_layer_c_fired", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("current_verified_citations_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_web_confidence", sa.Integer(), nullable=True),

        # Tier router output.
        sa.Column("shadow_tier", sa.Integer(), nullable=False),       # 1-4
        sa.Column("shadow_label", sa.String(32), nullable=False),     # 'verified' | 'industry_standard' | 'relaxed_web' | 'best_effort'
        sa.Column("shadow_answer", sa.Text(), nullable=True),         # the answer the router would have rendered (only differs from current for tier 2/inverted-tier-3)
        sa.Column("shadow_reason", sa.Text(), nullable=True),         # router's debug 'reason' string
        sa.Column("shadow_classifier_verdict", sa.String(16), nullable=True),  # 'yes' | 'no' | 'uncertain' | NULL
        sa.Column("shadow_classifier_reasoning", sa.Text(), nullable=True),
        sa.Column("shadow_self_consistency_pass", sa.Boolean(), nullable=True),
        sa.Column("shadow_classifier_latency_ms", sa.Integer(), nullable=True),
        sa.Column("shadow_self_consistency_latency_ms", sa.Integer(), nullable=True),
        sa.Column("shadow_total_latency_ms", sa.Integer(), nullable=True),
        sa.Column("shadow_error", sa.Text(), nullable=True),

        # Did current and shadow render the SAME answer? Computed at
        # insert time so admin filtering ("show me chats where the
        # tier router would have changed the surface") is fast.
        sa.Column("differs", sa.Boolean(), nullable=False, server_default=sa.text("false"), index=True),

        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),

        # Constrain shadow_tier to the valid 1-4 range and shadow_label
        # to the four known strings — fail loudly if a bug slips a bad
        # value through.
        sa.CheckConstraint(
            "shadow_tier BETWEEN 1 AND 4",
            name="tier_router_shadow_log_tier_range",
        ),
        sa.CheckConstraint(
            "shadow_label IN ('verified', 'industry_standard', 'relaxed_web', 'best_effort')",
            name="tier_router_shadow_log_label_valid",
        ),
        sa.CheckConstraint(
            "mode IN ('shadow', 'live')",
            name="tier_router_shadow_log_mode_valid",
        ),
    )

    # Composite index for the admin "show me all differing rows in the
    # last 7d, paginated by recency" query.
    op.create_index(
        "ix_tier_router_shadow_log_recent_differs",
        "tier_router_shadow_log",
        [sa.text("created_at DESC"), "differs"],
    )

    # Per-tier counts query — backs the admin headline metrics.
    op.create_index(
        "ix_tier_router_shadow_log_tier_recent",
        "tier_router_shadow_log",
        ["shadow_tier", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_tier_router_shadow_log_tier_recent", table_name="tier_router_shadow_log")
    op.drop_index("ix_tier_router_shadow_log_recent_differs", table_name="tier_router_shadow_log")
    op.drop_table("tier_router_shadow_log")
    op.drop_column("messages", "tier_metadata")

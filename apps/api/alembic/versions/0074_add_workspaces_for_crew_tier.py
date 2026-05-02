"""add workspaces + workspace_members for crew tier

Revision ID: 0074
Revises: 0073
Create Date: 2026-05-02

Sprint D6.49 — Crew tier scaffold.

A workspace is the unit of crew-tier billing AND the unit of vessel
context. One workspace = one vessel; the Owner holds the Stripe card,
Admins manage operational settings, Members use the workspace.

The crew-rotation reality: a vessel typically has TWO captains who
alternate (28-on/28-off, 60/60, etc.) along with their respective
crews. Both captains need persistent admin access; both crews are
permanent members. The workspace persists independent of either
captain's rotation status.

Owner / Admin / Member roles:
  Owner   — exactly one per workspace; holds Stripe customer + card;
            can transfer ownership; can remove their card (triggers
            card-pending state).
  Admin   — multiple allowed; can add/remove members, edit dossier
            settings, change member roles up to admin level; cannot
            transfer ownership or modify billing.
  Member  — read+write to dossier, ask questions, see shared chat.

Card-pending state:
  When the Owner transfers ownership OR removes their card without
  replacement, the workspace enters 'card_pending' for 30 days. During
  this window the workspace is read-only — chat history visible, no
  new chats / dossier entries / member changes. If a card is added
  before the deadline, status returns to 'active'. Otherwise status
  becomes 'archived' (90-day retention before purge).

Migration scope: schema only. UX, Stripe wiring, and the read-only
enforcement logic land in subsequent commits behind a feature flag.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0074"
down_revision: Union[str, None] = "0073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            -- Free-form name. We deliberately don't validate IMO numbers
            -- or anything vessel-specific — workspace is whatever the
            -- captain calls it. Keeps the data model simple and avoids
            -- painting into the "fleet management" corner.
            name VARCHAR(120) NOT NULL,

            -- Owner: holds the Stripe customer + card. Exactly one per
            -- workspace. Transfer is a billing-card swap, not a data move.
            owner_user_id UUID NOT NULL REFERENCES users(id) ON DELETE RESTRICT,

            -- Stripe linkage (nullable until subscription is set up).
            stripe_customer_id VARCHAR(64),
            stripe_subscription_id VARCHAR(64),

            -- Lifecycle state machine.
            --   active        → normal operation, billed
            --   trialing      → first 30 days included on upgrade
            --   card_pending  → owner transferred or removed card; 30-day
            --                   read-only grace before archival
            --   archived      → 30-day grace expired; 90-day retention
            --                   before purge if no card added
            --   canceled      → owner explicitly canceled; 90-day retention
            status VARCHAR(20) NOT NULL DEFAULT 'trialing',

            -- When the card_pending state was entered (used to compute
            -- the 30-day deadline). NULL outside that state.
            card_pending_started_at TIMESTAMPTZ,

            -- Soft seat cap (10 by default for the $99 tier; 20 for $149).
            seat_cap INTEGER NOT NULL DEFAULT 10,

            -- Internal-only flag — set TRUE for our own test workspaces
            -- during the staged rollout. The crew-tier UI is gated to
            -- internal users until we lift the flag.
            internal_only BOOLEAN NOT NULL DEFAULT FALSE,

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT workspaces_status_check CHECK (status IN (
                'active', 'trialing', 'card_pending', 'archived', 'canceled'
            ))
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspaces_owner_idx "
        "ON workspaces(owner_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspaces_status_idx "
        "ON workspaces(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspaces_stripe_subscription_idx "
        "ON workspaces(stripe_subscription_id) "
        "WHERE stripe_subscription_id IS NOT NULL"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_members (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL
                REFERENCES workspaces(id) ON DELETE CASCADE,
            user_id UUID NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,

            -- 'owner' | 'admin' | 'member'. Exactly one row per
            -- (workspace_id, user_id). The Owner role is also denormalized
            -- on workspaces.owner_user_id so we can enforce uniqueness +
            -- simplify billing-card lookup.
            role VARCHAR(16) NOT NULL,

            invited_by_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            joined_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT workspace_members_role_check CHECK (
                role IN ('owner', 'admin', 'member')
            ),
            CONSTRAINT workspace_members_unique UNIQUE (workspace_id, user_id)
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspace_members_workspace_idx "
        "ON workspace_members(workspace_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspace_members_user_idx "
        "ON workspace_members(user_id)"
    )

    # Workspace-scoped billing audit log. Records every transition of
    # owner_user_id, status, and Stripe subscription state. Useful for
    # debugging billing disputes and for surfacing transfer history in
    # the workspace settings UI.
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_billing_events (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL
                REFERENCES workspaces(id) ON DELETE CASCADE,
            event_type VARCHAR(40) NOT NULL,
            -- 'created', 'subscription_started', 'subscription_renewed',
            -- 'subscription_canceled', 'card_updated', 'owner_transferred',
            -- 'card_pending', 'card_resolved', 'archived', 'restored'
            actor_user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            -- Free-form JSON for context (old/new owner, old/new status,
            -- Stripe event id, etc.)
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspace_billing_events_workspace_idx "
        "ON workspace_billing_events(workspace_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_billing_events")
    op.execute("DROP TABLE IF EXISTS workspace_members")
    op.execute("DROP TABLE IF EXISTS workspaces")

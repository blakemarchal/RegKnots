"""add workspace_invites for pending-invite flow

Revision ID: 0079
Revises: 0078
Create Date: 2026-05-04

Sprint D6.53 — pending-invite + Wheelhouse-only signup flow.

Until now, /workspaces/{id}/members POST hard-failed when the invitee
didn't already have a RegKnots account, which made onboarding crew
impossible: the captain has to invite people who haven't heard of
RegKnots yet, not just existing users. This migration adds the
workspace_invites table so the API can:

  1. Store an invite for any email — registered or not.
  2. Email the invitee a tokenized link to claim it.
  3. Auto-attach them to the workspace on the next registration OR
     login (whichever happens first), as long as the email matches.

Seat-cap accounting:
  Pending invites (status='pending') count against workspaces.seat_cap
  alongside accepted members. Otherwise an admin could over-invite and
  the last invitee's accept would silently fail. The application code
  enforces this — the schema just records state.

Status state machine:
  pending   →  invitation issued, email sent, awaiting action
  accepted  →  user clicked link / signed up; row kept for audit
  declined  →  user explicitly declined; row kept for audit
  rescinded →  Owner/Admin pulled the invite back; row kept for audit
  expired   →  past expires_at without action; lazily transitioned by
               application code on read

Tokens are 32-byte URL-safe random strings; we store them
case-sensitively and treat them as unguessable. Any unique-violation
on (workspace_id, lower(email)) WHERE status='pending' means the
admin tried to re-invite someone with a still-active invite —
endpoint should return 409.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0079"
down_revision: Union[str, None] = "0078"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS workspace_invites (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id UUID NOT NULL
                REFERENCES workspaces(id) ON DELETE CASCADE,

            -- Lowercased on insert. We don't FK to users(email) because
            -- the whole point is that the invitee may not have an
            -- account yet.
            email TEXT NOT NULL,

            -- Role they'll receive when they accept. Same set as
            -- workspace_members.role minus 'owner'.
            role VARCHAR(16) NOT NULL,

            -- Random URL-safe token included in the invite email. The
            -- accept endpoint accepts either this token (link-click
            -- path) or matches by current_user.email (signed-in-after-
            -- registration path).
            token TEXT NOT NULL UNIQUE,

            invited_by_user_id UUID
                REFERENCES users(id) ON DELETE SET NULL,

            status VARCHAR(16) NOT NULL DEFAULT 'pending',

            expires_at TIMESTAMPTZ NOT NULL DEFAULT (now() + INTERVAL '14 days'),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            accepted_at TIMESTAMPTZ,
            declined_at TIMESTAMPTZ,
            rescinded_at TIMESTAMPTZ,
            -- The user_id that resulted from the accept (FK lets us
            -- show "joined as Mate Smith" in the audit log even after
            -- they're removed).
            accepted_by_user_id UUID
                REFERENCES users(id) ON DELETE SET NULL,

            CONSTRAINT workspace_invites_role_check CHECK (
                role IN ('admin', 'member')
            ),
            CONSTRAINT workspace_invites_status_check CHECK (status IN (
                'pending', 'accepted', 'declined', 'rescinded', 'expired'
            ))
        )
    """)

    # One ACTIVE invite per (workspace, email). Inactive rows (accepted/
    # declined/rescinded/expired) are excluded so re-invites work.
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS workspace_invites_active_unique
        ON workspace_invites (workspace_id, lower(email))
        WHERE status = 'pending'
    """)

    op.execute(
        "CREATE INDEX IF NOT EXISTS workspace_invites_email_idx "
        "ON workspace_invites (lower(email)) "
        "WHERE status = 'pending'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspace_invites_workspace_idx "
        "ON workspace_invites (workspace_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS workspace_invites_token_idx "
        "ON workspace_invites (token) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_invites")

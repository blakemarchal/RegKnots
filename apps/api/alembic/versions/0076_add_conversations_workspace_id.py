"""add conversations.workspace_id (nullable, opt-in)

Revision ID: 0076
Revises: 0075
Create Date: 2026-05-02

Sprint D6.49 — workspace-scoped chat. Adds an OPTIONAL workspace_id
column to conversations.

Iron-clad backward compatibility:
  - Column is NULL for every existing row.
  - Column is NULL by default for every new conversation.
  - User-scoped (personal) conversations are NEVER touched by workspace
    code paths. The same chat endpoint, with no workspace_id in the
    body, returns the same shape and behavior as before.
  - Permission check (in code, not enforceable at DB level): a user can
    read a conversation if they own it (user_id = me) OR if it's bound
    to a workspace they're a member of (workspace_id IN their workspaces).

The conversations.user_id column is preserved as the personal-context
key. workspace_id is purely additive and only set when a workspace
member explicitly creates a chat in the workspace's context.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0076"
down_revision: Union[str, None] = "0075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN IF NOT EXISTS workspace_id UUID "
        "REFERENCES workspaces(id) ON DELETE SET NULL"
    )
    # Partial index — only over workspace-scoped rows. Personal-tier
    # conversations are queried by user_id (existing index untouched);
    # workspace queries are O(workspace_size) which is small (<= 10
    # members) so a small index suffices.
    op.execute(
        "CREATE INDEX IF NOT EXISTS conversations_workspace_idx "
        "ON conversations(workspace_id, created_at DESC) "
        "WHERE workspace_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS conversations_workspace_idx")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS workspace_id")

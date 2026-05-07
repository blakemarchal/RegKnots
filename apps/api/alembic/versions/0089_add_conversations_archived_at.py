"""add conversations.archived_at for soft archive

Revision ID: 0089
Revises: 0088
Create Date: 2026-05-07

D6.80 — soft archive UX. Karynn flagged chat-history bloat:
power users will accumulate hundreds of conversations, the /history
list caps at 50, older threads disappear from view but stay in DB.

This migration adds `archived_at TIMESTAMPTZ NULL` so users can
hide stale conversations from /history without deleting them. The
audit + learning pipelines (hedge classifier, citation oracle,
analytics) keep training on archived rows the same as live ones —
the column is purely UI scope.

Indexed because the default /conversations list now filters
WHERE archived_at IS NULL (active conversations only). Without the
index, every list query would full-scan the conversations table.

No backfill needed — every existing row defaults to NULL (active).
Downgrade drops the index and the column; idempotent.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0089"
down_revision: Union[str, None] = "0088"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL"
    )
    # Partial index — only need to query the live (non-archived) rows
    # quickly. Archived browsing is rare; uses a sequential scan and
    # that's fine.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_conversations_active "
        "ON conversations (user_id, updated_at DESC) "
        "WHERE archived_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversations_active")
    op.execute("ALTER TABLE conversations DROP COLUMN IF EXISTS archived_at")

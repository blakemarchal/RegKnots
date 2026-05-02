"""add workspace handoff_note

Revision ID: 0078
Revises: 0077
Create Date: 2026-05-02

Sprint D6.49 — workspace handoff note. The rotation use case: outgoing
watch (e.g., Captain A leaving on rotation) leaves a free-form note
for the incoming watch (Captain B arriving) — vessel status, recent
PSC findings, equipment quirks, near-miss observations, anything the
next watch needs to know.

One note per workspace, edited in place. Last editor + timestamp
tracked so members can see who wrote what and when. No history /
versioning — the note is meant to be rolling, not an audit log.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0078"
down_revision: Union[str, None] = "0077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE workspaces "
        "ADD COLUMN IF NOT EXISTS handoff_note TEXT, "
        "ADD COLUMN IF NOT EXISTS handoff_note_updated_at TIMESTAMPTZ, "
        "ADD COLUMN IF NOT EXISTS handoff_note_updated_by_user_id UUID "
        "REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE workspaces "
        "DROP COLUMN IF EXISTS handoff_note, "
        "DROP COLUMN IF EXISTS handoff_note_updated_at, "
        "DROP COLUMN IF EXISTS handoff_note_updated_by_user_id"
    )

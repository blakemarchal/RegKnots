"""add users.verbosity_preference

Revision ID: 0065
Revises: 0064
Create Date: 2026-04-30

Sprint D6.33 — captures the user's preferred response style. Lets a busy
mariner ask for concise answers and a compliance attorney ask for deep
dives without typing the preference into every message.

Allowed values (validated in app code):
  brief     2-3 focused paragraphs, lead citation, offer to expand
  standard  current behavior (default for NULL — no special instruction)
  detailed  thorough, sectioned answers with applicability tables

Per-message override is shipped separately in D6.34 (chat request body).
This column captures only the persistent default.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS verbosity_preference TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS verbosity_preference")

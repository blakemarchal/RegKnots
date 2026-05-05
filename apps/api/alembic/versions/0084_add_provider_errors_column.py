"""add provider_errors JSONB column to web_fallback_responses

Revision ID: 0084
Revises: 0083
Create Date: 2026-05-05

D6.58 audit fix #2 — provider failure visibility.

The Slice 3 ensemble logs `ensemble_providers` (which providers
succeeded) but not WHY the missing ones failed. After the made-in-
china audit revealed Grok was silently 404-ing on a stale model
name, this column captures per-provider error reasons so the admin
can spot regressions without grepping journal lines.

Schema: JSONB shaped as { provider_name: error_string }, e.g.
    {"grok": "http_404", "gpt": "TimeoutError: ..."}
Empty {} or NULL means no failures (all three succeeded).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0084"
down_revision: Union[str, None] = "0083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE web_fallback_responses
            ADD COLUMN IF NOT EXISTS provider_errors JSONB
    """)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE web_fallback_responses "
        "DROP COLUMN IF EXISTS provider_errors"
    )

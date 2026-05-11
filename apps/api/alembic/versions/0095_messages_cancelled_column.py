"""add messages.cancelled column for D6.85 Stop button

Revision ID: 0095
Revises: 0094
Create Date: 2026-05-10

D6.85 Sprint — supports the Stop generation button (Fix C). When a
user aborts a chat mid-stream, the server saves whatever partial
content was streamed AND marks the assistant message as cancelled
so the UI can render it distinctly.

Nullable boolean defaulting to false:
  - false (or NULL) → normal completed message (today's behavior)
  - true            → user stopped generation mid-stream; content
                      is the partial output that was streamed to
                      the client before the abort
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0095"
down_revision: Union[str, None] = "0094"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "cancelled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "cancelled")

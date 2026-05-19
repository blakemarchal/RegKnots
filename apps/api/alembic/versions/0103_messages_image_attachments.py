"""add image_attachments jsonb column to messages

Revision ID: 0103
Revises: 0102
Create Date: 2026-05-19

Sprint D6.97 Phase 2 — image upload. Stores client-resized image
attachments inline with the user message so:

  1. The engine can pass them to the Anthropic multimodal API at
     synthesis time (no separate fetch).
  2. The user can scroll back through a conversation and see what
     they sent (thumbnails render alongside their message bubble).
  3. Cross-device sessions get the same attachments without
     localStorage shenanigans.

Schema:
  image_attachments jsonb NOT NULL DEFAULT '[]'::jsonb

Each list element is an object of shape:
  {
    "data_url": "data:image/jpeg;base64,...",  // client-resized to ≤1024px
    "mime":     "image/jpeg" | "image/png" | "image/webp",
    "width":    int,                            // pixel dims after resize
    "height":   int,
    "size_bytes": int                           // base64-decoded length
  }

Storage envelope:
  Hard server cap of 10 MB per image × 5 images per query = 50 MB max
  theoretical row size. In practice client resize lands each image
  ~200-500 KB → typical row 1-2.5 MB. Postgres jsonb TOAST handles
  this transparently.

Revert path:
  Set CHAT_IMAGE_UPLOAD_MODE=off in /opt/RegKnots/.env, restart
  regknots-api. Existing rows with image_attachments are harmless —
  the engine only consumes them when the flag is live.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0103"
down_revision: Union[str, None] = "0102"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE messages "
        "ADD COLUMN image_attachments jsonb NOT NULL DEFAULT '[]'::jsonb"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN image_attachments")

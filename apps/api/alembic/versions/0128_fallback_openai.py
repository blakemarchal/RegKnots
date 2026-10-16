"""messages.model_used: 'fallback_openai' for the OpenAI fallback after GPT-4o

Revision ID: 0128
Revises: 0127
Create Date: 2026-10-16

GPT-4o leaves the OpenAI API on 2027-01-14 (OpenAI's notice of 2026-10-14);
the fallback that answers when Claude is unavailable moves to gpt-6-luna
(rag/fallback.py, env OPENAI_FALLBACK_MODEL). Its answers are stored as one
generic alias, 'fallback_openai', so the next model change needs no migration.
'fallback_gpt4o' stays allowed (0115); no row has ever used it.

The live constraint was read before writing this (2026-10-16): haiku, sonnet,
opus, fallback_gpt4o.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0128"
down_revision: Union[str, None] = "0127"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_model_used_check")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT messages_model_used_check CHECK "
        "(model_used = ANY (ARRAY['haiku', 'sonnet', 'opus', 'fallback_gpt4o', 'fallback_openai']))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT IF EXISTS messages_model_used_check")
    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT messages_model_used_check CHECK "
        "(model_used = ANY (ARRAY['haiku', 'sonnet', 'opus', 'fallback_gpt4o']))"
    )

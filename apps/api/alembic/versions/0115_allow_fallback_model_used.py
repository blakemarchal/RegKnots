"""add 'fallback_gpt4o' to messages.model_used check constraint

Revision ID: 0115
Revises: 0114
Create Date: 2026-08-10

2026-08-10 prod log audit — the OpenAI fallback path has NEVER been able
to persist an answer. `_MODEL_ALIAS` in app/routers/chat.py maps the
fallback id to "fallback_gpt4o", but messages_model_used_check has been
('haiku','sonnet','opus') since 0001_initial_schema and was never
widened. So whenever Claude is unavailable and rag.engine falls back to
GPT-4o, the answer generates successfully (HTTP 200, real tokens spent)
and then dies at the INSERT with:

    asyncpg.exceptions.CheckViolationError: new row for relation
    "messages" violates check constraint "messages_model_used_check"

Observed live 2026-08-09: the Anthropic credit balance hit zero, every
Claude call returned 400, the fallback engaged as designed — and 13
consecutive answers for tylerswillette@gmail.com were generated, billed,
and thrown away across two conversations (08:09-08:44 UTC). The user
retried 12 times watching answers vanish, then stopped. `SELECT DISTINCT
model_used FROM messages` confirms zero 'fallback_gpt4o' rows have ever
been written.

This is the D6.73 lesson one layer down: that sprint caught the alias
map drifting from router.MODEL_MAP; this is the alias map drifting from
the DB constraint. The comment block above _MODEL_ALIAS documents the
former while the latter sat broken directly beneath it.

Mirrors the constraint-swap pattern of 0110 / 0111 / 0113 / 0114.

NOTE: downgrade() will fail if any 'fallback_gpt4o' rows exist by then —
delete or re-map them first. NULL is unaffected either way (a NULL
comparison yields NULL, not FALSE, so CHECK passes; the 558 pre-existing
NULL rows from the D6.73 era are untouched by this migration).
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0115"
down_revision: Union[str, None] = "0114"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_MODELS = "haiku', 'sonnet', 'opus', 'fallback_gpt4o"

_OLD_MODELS = "haiku', 'sonnet', 'opus"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE messages DROP CONSTRAINT messages_model_used_check"
    )
    op.execute(
        f"ALTER TABLE messages ADD CONSTRAINT messages_model_used_check "
        f"CHECK (model_used IN ('{_NEW_MODELS}'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE messages DROP CONSTRAINT messages_model_used_check"
    )
    op.execute(
        f"ALTER TABLE messages ADD CONSTRAINT messages_model_used_check "
        f"CHECK (model_used IN ('{_OLD_MODELS}'))"
    )

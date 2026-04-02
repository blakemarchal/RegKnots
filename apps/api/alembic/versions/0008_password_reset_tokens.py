"""add password_reset_tokens table

Revision ID: 0008
Revises: 0007
Create Date: 2026-04-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE password_reset_tokens (
            id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TIMESTAMPTZ NOT NULL,
            used       BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX idx_password_reset_tokens_user_id ON password_reset_tokens(user_id)"
    ))
    op.execute(sa.text(
        "CREATE INDEX idx_password_reset_tokens_token_hash ON password_reset_tokens(token_hash) WHERE NOT used"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS password_reset_tokens CASCADE"))

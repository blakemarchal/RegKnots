"""add citation_errors table

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-31

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("""
            CREATE TABLE citation_errors (
                id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                conversation_id     UUID REFERENCES conversations(id),
                message_content     TEXT,
                unverified_citation TEXT,
                model_used          TEXT,
                created_at          TIMESTAMPTZ DEFAULT now()
            )
        """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS citation_errors"))

"""add GIN trigram index on regulations.full_text

Revision ID: 0033
Revises: 0032
Create Date: 2026-04-10

Enables pg_trgm and creates a GIN trigram index to accelerate ILIKE keyword
searches used by the hybrid retriever.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_regulations_fulltext_trgm "
        "ON regulations USING gin (full_text gin_trgm_ops)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_regulations_fulltext_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

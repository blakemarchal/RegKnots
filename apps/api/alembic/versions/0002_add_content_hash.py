"""add content_hash and unique chunk index

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # TEXT NULL — no NOT NULL, no default; backfilled after first ingest
    op.execute(sa.text("ALTER TABLE regulations ADD COLUMN content_hash TEXT"))

    # Replace the non-unique (source, section_number) index with a unique
    # (source, section_number, chunk_index) index — required for ON CONFLICT upserts.
    op.execute(sa.text("DROP INDEX IF EXISTS idx_regulations_source_section"))
    op.execute(sa.text("""
        CREATE UNIQUE INDEX idx_regulations_unique_chunk
        ON regulations(source, section_number, chunk_index)
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS idx_regulations_unique_chunk"))
    op.execute(sa.text(
        "CREATE INDEX idx_regulations_source_section ON regulations(source, section_number)"
    ))
    op.execute(sa.text("ALTER TABLE regulations DROP COLUMN IF EXISTS content_hash"))

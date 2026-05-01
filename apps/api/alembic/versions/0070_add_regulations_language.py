"""add regulations.language column

Revision ID: 0070
Revises: 0069
Create Date: 2026-05-01

Sprint D6.46 — multilingual ingest. Annotate each row with its source
language (ISO 639-1) so the UI can flag non-English chunks and the
retriever can optionally filter by language.

text-embedding-3-small is multilingual-capable: cross-lingual cosine
similarity for FR/DE/ES/IT vs EN is 0.45-0.89 (vs 0.18 unrelated
baseline), so existing chunks remain retrievable from translated
queries without re-embedding. The new column is purely a metadata flag.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0070"
down_revision: Union[str, None] = "0069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Column with safe default. All existing rows are English.
    op.execute(
        "ALTER TABLE regulations "
        "ADD COLUMN IF NOT EXISTS language VARCHAR(8) NOT NULL DEFAULT 'en'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS regulations_language_idx "
        "ON regulations(language)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS regulations_language_idx")
    op.execute("ALTER TABLE regulations DROP COLUMN IF EXISTS language")

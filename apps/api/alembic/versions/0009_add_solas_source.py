"""confirm solas in regulations source constraint; add ingest CLI support

Revision ID: 0009
Revises: 0008
Create Date: 2026-04-02

'solas' was included in the regulations_source_check constraint from
migration 0001 (initial schema).  This migration is a no-op for the DB
constraint — it serves as a version-history marker for when the full SOLAS
text-based ingest pipeline (packages/ingest/ingest/sources/solas.py) was
wired into the CLI.

No data migration or schema change is required.
"""

from typing import Sequence, Union

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 'solas' is already present in regulations_source_check from migration 0001.
    # Nothing to do.
    pass


def downgrade() -> None:
    pass

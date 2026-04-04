"""add revoked_at timestamp to refresh_tokens

Revision ID: 0016
Revises: 0015
Create Date: 2026-04-04

Tracks when a refresh token was revoked, enabling race-condition
grace window during concurrent token rotation.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE refresh_tokens ADD COLUMN revoked_at TIMESTAMPTZ"
    ))


def downgrade() -> None:
    op.execute(sa.text(
        "ALTER TABLE refresh_tokens DROP COLUMN revoked_at"
    ))

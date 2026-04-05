"""create pilot_survey_responses table

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-04

Stores in-app pilot feedback questionnaire responses.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        CREATE TABLE pilot_survey_responses (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            overall_rating INTEGER NOT NULL CHECK (overall_rating BETWEEN 1 AND 5),
            usefulness TEXT,
            favorite_feature TEXT,
            missing_feature TEXT,
            would_subscribe BOOLEAN,
            price_feedback TEXT,
            vessel_type_used TEXT,
            additional_comments TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """))
    op.execute(sa.text(
        "CREATE INDEX idx_pilot_survey_user ON pilot_survey_responses(user_id)"
    ))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS pilot_survey_responses"))

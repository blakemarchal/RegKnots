"""create vessel_documents table

Revision ID: 0019
Revises: 0018
Create Date: 2026-04-05

Stores uploaded vessel documents (COI, safety certs, etc.) and
extracted structured data from Claude Vision.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        sa.text("""
        CREATE TABLE vessel_documents (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            vessel_id UUID NOT NULL REFERENCES vessels(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            document_type TEXT NOT NULL CHECK (
                document_type IN (
                    'coi', 'safety_equipment', 'safety_construction',
                    'safety_radio', 'isps', 'ism', 'other'
                )
            ),
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_size INTEGER,
            mime_type TEXT,
            extracted_data JSONB DEFAULT '{}',
            extraction_status TEXT NOT NULL DEFAULT 'pending' CHECK (
                extraction_status IN ('pending', 'extracted', 'confirmed', 'failed')
            ),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """)
    )
    op.execute(
        sa.text("CREATE INDEX idx_vessel_documents_vessel ON vessel_documents(vessel_id)")
    )
    op.execute(
        sa.text("CREATE INDEX idx_vessel_documents_user ON vessel_documents(user_id)")
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER vessel_documents_updated_at
            BEFORE UPDATE ON vessel_documents
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """)
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS vessel_documents_updated_at ON vessel_documents"))
    op.execute(sa.text("DROP TABLE IF EXISTS vessel_documents"))

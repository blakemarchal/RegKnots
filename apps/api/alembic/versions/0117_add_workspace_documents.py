"""add workspace_documents + workspace_document_chunks

Revision ID: 0117
Revises: 0116
Create Date: 2026-09-27

Company documents in fleet chat (spec: docs/specs/company-documents-2026-09-27.md).
A workspace uploads its own SMS / TSMS manual and procedures; workspace chats
retrieve from them alongside the regulations and cite them as
[Company: <title> §<section>].

Tenancy: these rows never go in `regulations`. Every chunk carries its
workspace_id and every read filters on it, so one fleet's manual can't
surface in another fleet's chat. Deleting a workspace or a document removes
its chunks (ON DELETE CASCADE); the upload itself is deleted by the API.

  workspace_documents        one row per upload; status pending -> ready | failed
  workspace_document_chunks  heading-split, token-bounded text + embedding
                             (text-embedding-3-small, 1536 dims). Searched by an
                             exact scan within one workspace (btree on
                             workspace_id), so no ANN index is needed.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0117"
down_revision: Union[str, None] = "0116"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE workspace_documents (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            uploaded_by   UUID REFERENCES users(id) ON DELETE SET NULL,
            filename      TEXT NOT NULL,
            title         TEXT NOT NULL,
            mime_type     TEXT NOT NULL,
            file_path     TEXT NOT NULL,
            size_bytes    INTEGER NOT NULL,
            pages         INTEGER,
            chunk_count   INTEGER NOT NULL DEFAULT 0,
            status        TEXT NOT NULL DEFAULT 'pending'
                          CHECK (status IN ('pending', 'ready', 'failed')),
            error         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_workspace_documents_workspace ON workspace_documents(workspace_id)")
    op.execute("""
        CREATE TABLE workspace_document_chunks (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id   UUID NOT NULL REFERENCES workspace_documents(id) ON DELETE CASCADE,
            workspace_id  UUID NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
            section       TEXT NOT NULL,
            chunk_index   INTEGER NOT NULL,
            text          TEXT NOT NULL,
            embedding     vector(1536) NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_workspace_document_chunks_workspace ON workspace_document_chunks(workspace_id)")
    op.execute("CREATE INDEX idx_workspace_document_chunks_document ON workspace_document_chunks(document_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS workspace_document_chunks")
    op.execute("DROP TABLE IF EXISTS workspace_documents")

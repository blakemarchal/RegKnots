"""add user_documents + user_document_chunks, messages.document_ids

Revision ID: 0121
Revises: 0120
Create Date: 2026-10-05

PDF and Word uploads in chat (spec: docs/specs/chat-document-upload-2026-10-05.md).
A user attaches their own document (an SMS manual, a procedure, a checklist)
to a question; RegKnot reads it, answers with it, and keeps it in the user's
account when an internal check finds it maritime (kept = true). A document the
check finds not maritime serves the conversation it came in and is deleted
after 7 days (delete_after; the daily purge task removes it).

Tenancy: these rows never go in `regulations`, and they are kept apart from
the workspace (company) documents. Every chunk carries its user_id and every
read filters on it, so one user's document can't surface for anyone else.
Deleting a user or a document removes its chunks (ON DELETE CASCADE); the
upload itself is deleted by the API or the purge task.

  user_documents        one row per upload; status pending -> ready | failed;
                        doc_type / maritime / summary from the internal check
  user_document_chunks  heading-split, token-bounded text + embedding
                        (text-embedding-3-small, 1536 dims); exact scan within
                        one user (btree on user_id), no ANN index needed
  messages.document_ids the documents attached to a user message
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0121"
down_revision: Union[str, None] = "0120"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE user_documents (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
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
            doc_type      TEXT,
            maritime      BOOLEAN,
            summary       TEXT,
            kept          BOOLEAN NOT NULL DEFAULT false,
            delete_after  TIMESTAMPTZ,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_used_at  TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_user_documents_user ON user_documents(user_id, created_at DESC)")
    op.execute("CREATE INDEX idx_user_documents_delete_after ON user_documents(delete_after) WHERE delete_after IS NOT NULL")
    op.execute("""
        CREATE TABLE user_document_chunks (
            id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id   UUID NOT NULL REFERENCES user_documents(id) ON DELETE CASCADE,
            user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            section       TEXT NOT NULL,
            chunk_index   INTEGER NOT NULL,
            position      INTEGER NOT NULL,   -- order in the whole document (outline, admin text)
            text          TEXT NOT NULL,
            embedding     vector(1536) NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_user_document_chunks_user ON user_document_chunks(user_id)")
    op.execute("CREATE INDEX idx_user_document_chunks_document ON user_document_chunks(document_id)")
    op.execute("ALTER TABLE messages ADD COLUMN document_ids UUID[]")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN IF EXISTS document_ids")
    op.execute("DROP TABLE IF EXISTS user_document_chunks")
    op.execute("DROP TABLE IF EXISTS user_documents")

"""regulation_vectors: the embeddings stored in-line for exact group scans (2026-10-17).

Every search runs ~23 per-group queries that compute the distance to every
embedding in the group (exact scans; see docs/sprint-audits/
latency-audit-2026-10-17.md). In `regulations` the 6 KB vectors live out of
line (TOAST), and fetching them was ~90% of a search's database time.
This table keeps a copy stored in-line (STORAGE PLAIN), so the same scan reads
it straight from the page: same rows in the same order, about 3x less work
(measured on prod: one search 1.8 s -> 0.48 s, four at once 5.3 s -> 1.6 s).

Kept in step by a trigger on regulations (insert, and update of embedding /
source / jurisdictions) and ON DELETE CASCADE. The retriever checks at startup
that it holds every embedded row and otherwise uses the old query
(rag.retriever._side_table_ready). The nightly backup leaves its data out
(scripts/backup_postgres.sh); after a restore it is rebuilt with the INSERT
below (docs/runbooks/db-restore.md).

Revision ID: 0131
Revises: 0130
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0131"
down_revision: Union[str, None] = "0130"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE regulation_vectors (
            id            UUID PRIMARY KEY REFERENCES regulations(id) ON DELETE CASCADE,
            source        TEXT NOT NULL,
            jurisdictions TEXT[],
            embedding     vector(1536) NOT NULL
        )
        """
    )
    op.execute("ALTER TABLE regulation_vectors ALTER COLUMN embedding SET STORAGE PLAIN")
    op.execute(
        """
        CREATE FUNCTION regulation_vectors_sync() RETURNS trigger AS $$
        BEGIN
            IF NEW.embedding IS NULL THEN
                DELETE FROM regulation_vectors WHERE id = NEW.id;
            ELSE
                INSERT INTO regulation_vectors (id, source, jurisdictions, embedding)
                VALUES (NEW.id, NEW.source, NEW.jurisdictions, NEW.embedding)
                ON CONFLICT (id) DO UPDATE
                    SET source = EXCLUDED.source,
                        jurisdictions = EXCLUDED.jurisdictions,
                        embedding = EXCLUDED.embedding;
            END IF;
            RETURN NULL;
        END
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_regulation_vectors_sync
        AFTER INSERT OR UPDATE OF embedding, source, jurisdictions ON regulations
        FOR EACH ROW EXECUTE FUNCTION regulation_vectors_sync()
        """
    )
    # Ordered by source so each group's rows sit together on disk.
    op.execute(
        """
        INSERT INTO regulation_vectors (id, source, jurisdictions, embedding)
        SELECT id, source, jurisdictions, embedding FROM regulations
        WHERE embedding IS NOT NULL ORDER BY source, id
        """
    )
    op.execute("CREATE INDEX idx_regulation_vectors_source ON regulation_vectors (source)")
    op.execute("ANALYZE regulation_vectors")


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_regulation_vectors_sync ON regulations")
    op.execute("DROP FUNCTION IF EXISTS regulation_vectors_sync()")
    op.execute("DROP TABLE IF EXISTS regulation_vectors")

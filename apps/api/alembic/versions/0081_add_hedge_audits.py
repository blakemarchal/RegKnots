"""add hedge_audits for the mariner-in-the-loop feedback table

Revision ID: 0081
Revises: 0080
Create Date: 2026-05-04

Sprint D6.58 Slice 2 — auto-audit on hedges.

Every time the model hedges (corpus didn't have a confident answer
OR fallback only surfaced a 'reference' tier link), we fire a Haiku
classifier asynchronously and write a row here. The row captures:

  - the user's query
  - what we retrieved (top-K snapshot, JSON)
  - the classifier's verdict (one of 7 categories)
  - the classifier's reasoning + recommended fix
  - a workflow status field so Karynn / admin can mark each audit
    as fixed / won't fix / duplicate, and add notes

The seven classifications:
  VOCAB        — user term mismatch with corpus phrasing
  INTENT       — query intent landed on the wrong section type
  RANKING      — right section retrieved but ranked too low
  COSINE       — top-K all genuinely irrelevant (retrieval gap)
  CORPUS_GAP   — answer not in corpus at all (ingest source)
  JURISDICTION — wrong scope (US for non-US flag, etc.)
  OTHER        — doesn't fit; flag for human review

Marketing payoff: this becomes the structured proof of the
"mariner-in-the-loop" claim. The admin UI shows ongoing fix work;
the weekly digest emails the Owner. Future addition: a public
"Recent corrections" feed on the landing page.

Cost: ~$0.001 per classification (Haiku). At ~5% hedge rate × 1k
queries/day, that's ~$0.05/day. Negligible.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0081"
down_revision: Union[str, None] = "0080"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS hedge_audits (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),

            -- Source linkage. message_id is the assistant message that
            -- hedged. user_id is the asker. Both nullable so audits
            -- survive deletions; the audit row has its own retained
            -- snapshot so we can still act on it after the source is
            -- gone.
            conversation_id UUID
                REFERENCES conversations(id) ON DELETE SET NULL,
            message_id UUID,
            user_id UUID
                REFERENCES users(id) ON DELETE SET NULL,

            query TEXT NOT NULL,

            -- Snapshot of what retrieval returned (top-K). JSON array
            -- of {source, section_number, section_title, similarity}.
            -- Stored verbatim so we can replay the failure offline.
            top_retrieved_sections JSONB NOT NULL DEFAULT '[]'::jsonb,

            -- Web fallback context (if any). NULL if no fallback fired
            -- or fallback was blocked. surface_tier = 'verified' |
            -- 'reference' from the new D6.58 model.
            web_fallback_id UUID,
            web_surface_tier VARCHAR(16),

            -- Classifier output. classification is the bucket;
            -- reasoning is the model's one-paragraph explanation;
            -- recommendation is its suggested next step ("add 'X' to
            -- synonyms.py" / "ingest 33 CFR Part Y").
            classification VARCHAR(32) NOT NULL,
            classifier_reasoning TEXT,
            recommendation TEXT,
            classifier_model VARCHAR(40),

            -- Workflow. status starts open; admin transitions via UI.
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            admin_notes TEXT,
            fixed_at TIMESTAMPTZ,
            fixed_by_user_id UUID
                REFERENCES users(id) ON DELETE SET NULL,
            fix_commit_sha VARCHAR(64),  -- optional traceability

            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

            CONSTRAINT hedge_audits_classification_check CHECK (
                classification IN (
                    'VOCAB','INTENT','RANKING','COSINE',
                    'CORPUS_GAP','JURISDICTION','OTHER'
                )
            ),
            CONSTRAINT hedge_audits_status_check CHECK (
                status IN ('open','fixed','wontfix','duplicate')
            )
        )
    """)

    # Most-common query: open audits, newest first, filterable by class.
    op.execute(
        "CREATE INDEX IF NOT EXISTS hedge_audits_status_class_idx "
        "ON hedge_audits (status, classification, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS hedge_audits_created_idx "
        "ON hedge_audits (created_at DESC)"
    )
    # For "show me all open audits for this conversation" if a user
    # complains and we want to see the audit trail.
    op.execute(
        "CREATE INDEX IF NOT EXISTS hedge_audits_conv_idx "
        "ON hedge_audits (conversation_id) "
        "WHERE conversation_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hedge_audits")

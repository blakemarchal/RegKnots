"""seo_pages: plain-English regulation pages for search

Revision ID: 0124
Revises: 0123
Create Date: 2026-10-14

Growth plan step 3 (docs/specs/growth-plan-2026-10-14.md). One row per public
page at /regs/<slug>: a U.S. regulation section (46 / 33 CFR, the Coast
Guard's Navigation Rules, an NVIC's main body), the section text it explains
and the explanation app/seo_pages.py wrote for it.

  status   draft      selected, not yet written
           published  every automated check passed; served
           held       a check failed or the regulation text changed; not served
           retired    the section left the corpus or the selection
  checks   each check's result and the failures, for the admin review list
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0124"
down_revision: Union[str, None] = "0123"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE seo_pages (
            id               BIGSERIAL PRIMARY KEY,
            slug             TEXT NOT NULL UNIQUE,
            collection       TEXT NOT NULL,
            source           TEXT NOT NULL,
            section_number   TEXT NOT NULL,
            section_title    TEXT,
            display_number   TEXT NOT NULL,
            title            TEXT,
            meta_description TEXT,
            content          JSONB,
            source_text      TEXT NOT NULL,
            source_hash      TEXT NOT NULL,
            up_to_date_as_of DATE,
            priority         INTEGER NOT NULL DEFAULT 0,
            status           TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft', 'published', 'held', 'retired')),
            checks           JSONB,
            model            TEXT,
            generated_at     TIMESTAMPTZ,
            published_at     TIMESTAMPTZ,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (source, section_number)
        )
        """
    )
    op.execute("CREATE INDEX ix_seo_pages_collection_status ON seo_pages (collection, status)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS seo_pages")

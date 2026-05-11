"""add citation_lookups telemetry table

Revision ID: 0096
Revises: 0095
Create Date: 2026-05-11

D6.88 Phase 1 — every chip click that hits the regulations lookup
endpoint writes a row here. Fields:

  user_id        : the caller (NULL if the user was deleted later)
  source         : e.g. 'cfr_46', 'solas', 'stcw', 'imdg'
  section_number : the exact identifier the chip carried
  found          : whether the lookup resolved to a real corpus row
                   (false = 404 — useful signal for the granularity
                   audit we'll run before Phase 2 ingest work)
  created_at     : timestamp

Two reasons this exists:

1. Operational telemetry — answers "are mariners actually clicking
   the chips, and on which regulations?" The retrieval team uses
   this to prioritize the next round of corpus ingest and to
   measure the impact of the Phase 1 copyright-filter loosening.

2. Defensive posture — if IMO Publishing ever reaches out about
   our Option B (full-text for IMO sources), we have the access
   pattern data to substantiate "this is a compliance tool, not
   a content service." Median user clicks N regulations per
   session, not thousands.

Fire-and-forget from the request path — failures never block
the response.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0096"
down_revision: Union[str, None] = "0095"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "citation_lookups",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id", sa.dialects.postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("section_number", sa.Text(), nullable=False),
        sa.Column("found", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"), nullable=False,
        ),
    )
    # User-bounded recent activity — backs "did this user click an
    # unusual number of regulations in the last hour" type queries.
    op.create_index(
        "ix_citation_lookups_user_recent",
        "citation_lookups",
        ["user_id", sa.text("created_at DESC")],
    )
    # Aggregate-by-source activity over time — backs the admin
    # dashboard rollup that will land when Phase 2 needs evidence.
    op.create_index(
        "ix_citation_lookups_source_recent",
        "citation_lookups",
        ["source", sa.text("created_at DESC")],
    )
    # Filter rows where the lookup 404'd — directly answers "which
    # citations are mariners clicking that we don't have at the
    # granularity they wrote?" This is the Phase 2 prioritization
    # signal.
    op.create_index(
        "ix_citation_lookups_not_found",
        "citation_lookups",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("found IS FALSE"),
    )


def downgrade() -> None:
    op.drop_index("ix_citation_lookups_not_found", table_name="citation_lookups")
    op.drop_index("ix_citation_lookups_source_recent", table_name="citation_lookups")
    op.drop_index("ix_citation_lookups_user_recent", table_name="citation_lookups")
    op.drop_table("citation_lookups")

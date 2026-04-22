"""add nmc_monitor_seen_urls table

Revision ID: 0046
Revises: 0045
Create Date: 2026-04-22

Dedicated tracking table for the weekly NMC document monitor. Replaces
the previous pattern of storing seen URLs inside the user-facing
`notifications` table under `notification_type='nmc_memo'`, which had
two problems:

  1. Cold-start spam: if the notifications table was purged (e.g. after
     Sprint B3 rollback tooling), the scraper saw every PDF on the NMC
     site as "new" and inserted one user-facing banner per PDF. On
     2026-04-22 that meant 221 banners in one run.

  2. Category confusion: the scraper produces admin-ops signal
     ("consider ingesting this new doc"), not user-facing regulatory
     updates. Putting that signal in `notifications` conflated the two
     audiences.

This table is monitor-only — no user-facing read path touches it. The
`notification_type='nmc_memo'` path is fully retired in Sprint D1.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0046"
down_revision: Union[str, None] = "0045"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS nmc_monitor_seen_urls (
            url TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            source_page TEXT NOT NULL,
            first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_nmc_monitor_first_seen "
        "ON nmc_monitor_seen_urls (first_seen_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_nmc_monitor_first_seen")
    op.execute("DROP TABLE IF EXISTS nmc_monitor_seen_urls")

"""persist hedge-judge reasoning on tier_router_shadow_log

Revision ID: 0098
Revises: 0097
Create Date: 2026-05-13

Sprint D6.92 — calibration audit visibility.

The tier router shadow log already persists `current_judge_verdict`
(complete_miss / partial_miss / precision_callout / false_hedge) but
NOT the judge's `reasoning` field — the 1-2 sentence explanation
Haiku returns alongside its verdict. Without the reasoning we can't
distinguish "the judge correctly identified a corpus gap" from "the
judge mis-rated a confident, well-cited answer."

Three documented cases of the latter so far (Karynn ETA-change
2026-05-11, Karynn fire-extinguisher 2026-05-11, Kenan fire-doors
2026-05-13) — all rated complete_miss despite 5+ verified citations
and confident substantive responses. Adding this column so the next
audit pass has the why, not just the what.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0098"
down_revision: Union[str, None] = "0097"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tier_router_shadow_log "
        "ADD COLUMN IF NOT EXISTS current_judge_reasoning TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tier_router_shadow_log "
        "DROP COLUMN IF EXISTS current_judge_reasoning"
    )

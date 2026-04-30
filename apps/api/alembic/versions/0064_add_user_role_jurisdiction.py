"""add users.persona and users.jurisdiction_focus

Revision ID: 0064
Revises: 0063
Create Date: 2026-04-30

Sprint D6.31 — captures user persona and primary jurisdiction so the
RAG prompt can scope answers correctly even when a user has no vessel
profile (teachers, instructors, students, shore-side compliance).

Note on naming: `users.role` already exists with values
{captain, mate, engineer, chief_engineer, other} — that's the
shipboard professional role captured at registration. We add
`persona` here as a separate axis (mariner / teacher / shore-side /
attorney / cadet / other) since the same captain might be using
RegKnot in either an operational or pedagogical context. Both fields
informs the prompt; they don't replace each other.

Both columns are nullable. Existing users keep NULL until they fill
them in via account settings. New users see the optional Step 0 in
the welcome flow that collects them.

Allowed values are validated in app code rather than via CHECK
constraints so adding a new persona or jurisdiction in the future is
a code-only change (no migration). Reference list:

  persona:
    mariner_shipboard       Mariner / shipboard
    teacher_instructor      Teacher / instructor
    shore_side_compliance   Shore-side compliance
    legal_consultant        Maritime attorney / consultant
    cadet_student           Cadet / student
    other                   Other

  jurisdiction_focus:
    us, uk, au, sg, hk, no, lr, mh, bs, international_mixed
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0064"
down_revision: Union[str, None] = "0063"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS persona TEXT")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS jurisdiction_focus TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS jurisdiction_focus")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS persona")

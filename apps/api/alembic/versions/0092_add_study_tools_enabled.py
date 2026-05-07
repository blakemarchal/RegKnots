"""add users.study_tools_enabled column for Study Tools nav visibility

Revision ID: 0092
Revises: 0091
Create Date: 2026-05-07

D6.83 Sprint A follow-up — per-user toggle that hides "Quizzes & Guides"
from the hamburger menu when off. Defaulted on for student / teacher
personas, off for everyone else.

Column is NULLABLE on purpose:
  - NULL  → user has never explicitly chosen; backend resolves via
            persona-based default
  - true  → explicitly enabled
  - false → explicitly disabled

Backfill (this migration):
  - persona ∈ {'cadet_student','teacher_instructor'}  → true
  - all other existing users                          → false

After this migration the resolution rule is:
  - If column is non-NULL → use it as the source of truth
  - If column is NULL (only possible after this point if a brand-new
    user signs up but hasn't picked a persona yet) → default false
    until they pick a persona, at which point the persona endpoint
    seeds the column.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0092"
down_revision: Union[str, None] = "0091"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("study_tools_enabled", sa.Boolean(), nullable=True),
    )

    # Backfill existing users so the toggle shows the right state on
    # first page load after deploy. Done as two UPDATE statements
    # (no ELSE branch) so any user with NULL persona stays NULL and
    # falls into the "default false" bucket of the resolver.
    op.execute(
        """
        UPDATE users
        SET study_tools_enabled = TRUE
        WHERE persona IN ('cadet_student', 'teacher_instructor')
          AND study_tools_enabled IS NULL
        """
    )
    op.execute(
        """
        UPDATE users
        SET study_tools_enabled = FALSE
        WHERE (persona IS NULL
               OR persona NOT IN ('cadet_student', 'teacher_instructor'))
          AND study_tools_enabled IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("users", "study_tools_enabled")

"""add email verification fields to users

Revision ID: 0025
Revises: 0024
Create Date: 2026-04-06

Adds soft email verification:
  - email_verified (default FALSE)
  - email_verification_token
  - email_verification_sent_at

Existing users are backfilled as verified so current pilot users are not
affected. New registrations start unverified.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("FALSE"),
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verification_token", sa.Text(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verification_sent_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
        ),
    )

    # Backfill all existing users as verified (pilot users are real)
    op.execute("UPDATE users SET email_verified = TRUE WHERE created_at < NOW()")


def downgrade() -> None:
    op.drop_column("users", "email_verification_sent_at")
    op.drop_column("users", "email_verification_token")
    op.drop_column("users", "email_verified")

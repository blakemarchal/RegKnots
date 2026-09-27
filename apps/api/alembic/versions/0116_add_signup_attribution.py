"""add users.signup_source + users.signup_attribution

Revision ID: 0116
Revises: 0115
Create Date: 2026-09-26

First-touch marketing attribution for signups. On 2026-09-26 none of the
64 external users had a recorded source, so there was no way to tell
which channel brought anyone in, or whether outreach works.

users.referral_source is NOT reused for this: it drives the charity
tithe split and grants lifetime promo pricing (Sprint D6.3b), so a
marketing code stored there would hand out discounts.

Columns:
  signup_source       text NULL   one label for grouping, e.g.
                                  "src:ob-3f9a", "utm:newsletter/email/oct",
                                  "referrer:facebook.com", "direct".
                                  NULL = signed up before this existed, or
                                  from a client that sent no attribution.
  signup_attribution  jsonb NULL  the raw first-touch fields (UTM params,
                                  src, ref, referrer_host, landing_path,
                                  first_seen_at), each capped at 120 chars.

Both are written once, at registration (app/routers/auth.py).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0116"
down_revision: Union[str, None] = "0115"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("signup_source", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("signup_attribution", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "signup_attribution")
    op.drop_column("users", "signup_source")

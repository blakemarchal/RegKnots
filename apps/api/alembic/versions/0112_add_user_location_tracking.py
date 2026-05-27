"""add user location-tracking columns

Revision ID: 0112
Revises: 0111
Create Date: 2026-05-27

Sprint D6.97 #56 — opt-in GPS persistence. Per Blake (2026-05-27,
post-Karynn whale-zones review):

  v1 scope: storage only. Schema + toggle + POST endpoint + whale-
  zones page sends when toggle is on. NO retrieval-time integration,
  NO alert system. Prove the consent + capture path works before
  wiring up consumption.

Columns:
  location_tracking_enabled  bool NOT NULL default false
    User has explicitly opted in via the account-page toggle.
  last_known_lat              double precision NULL
  last_known_lon              double precision NULL
  last_known_accuracy_m       double precision NULL
  last_known_at               timestamptz NULL
  last_known_source           text NULL  ('whale_zones' today; could
                                          add 'chat' / 'background'
                                          later without schema change)

Design: ONE row per user, most-recent position only. NO history table.
If we later need history (e.g., for retrospective "you crossed into
zone X at 14:32" alerts), we'll add a sparse user_location_history
table with explicit retention.

Privacy posture: the columns can only populate when
location_tracking_enabled = true. POST /users/me/location enforces
that gate. Setting the toggle OFF nulls the columns server-side
(handled in the API layer).
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0112"
down_revision: Union[str, None] = "0111"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "location_tracking_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column("users", sa.Column("last_known_lat", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("last_known_lon", sa.Float(), nullable=True))
    op.add_column("users", sa.Column("last_known_accuracy_m", sa.Float(), nullable=True))
    op.add_column(
        "users",
        sa.Column("last_known_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("users", sa.Column("last_known_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_known_source")
    op.drop_column("users", "last_known_at")
    op.drop_column("users", "last_known_accuracy_m")
    op.drop_column("users", "last_known_lon")
    op.drop_column("users", "last_known_lat")
    op.drop_column("users", "location_tracking_enabled")

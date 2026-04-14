"""add reg_alert_sources to notification_preferences default

Revision ID: 0038
Revises: 0037
Create Date: 2026-04-13

Extends the notification_preferences JSONB default to include
per-source immediate regulation alerts. Existing users keep
their current prefs — the API handles missing keys gracefully.
The new default includes all sources so new users get alerts
for everything by default.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0038"
down_revision: Union[str, None] = "0037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NEW_DEFAULT = (
    '{"cert_expiry_reminders": true, "cert_expiry_days": [90, 30, 7], '
    '"reg_change_digest": true, "reg_digest_frequency": "weekly", '
    '"reg_alert_sources": ["cfr_33", "cfr_46", "cfr_49", "nvic", "colregs", "solas", "stcw", "ism"]}'
)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE users ALTER COLUMN notification_preferences SET DEFAULT '{_NEW_DEFAULT}'::jsonb"
    )


def downgrade() -> None:
    _OLD_DEFAULT = (
        '{"cert_expiry_reminders": true, "cert_expiry_days": [90, 30, 7], '
        '"reg_change_digest": true, "reg_digest_frequency": "weekly"}'
    )
    op.execute(
        f"ALTER TABLE users ALTER COLUMN notification_preferences SET DEFAULT '{_OLD_DEFAULT}'::jsonb"
    )

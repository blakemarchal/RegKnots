"""create notifications + user dismissal tracking

Revision ID: 0031
Revises: 0030
Create Date: 2026-04-08

Adds in-app notification banners (regulation updates, system announcements).
Tracks per-user dismissals so once dismissed a banner stays gone.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE notifications (
            id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            title             TEXT NOT NULL,
            body              TEXT NOT NULL,
            notification_type TEXT NOT NULL DEFAULT 'regulation_update',
            source            TEXT,
            link_url          TEXT,
            is_active         BOOLEAN NOT NULL DEFAULT true,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_notifications_active ON notifications(is_active, created_at DESC)"
    )

    op.execute(
        """
        CREATE TABLE user_notification_dismissals (
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            notification_id UUID NOT NULL REFERENCES notifications(id) ON DELETE CASCADE,
            dismissed_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (user_id, notification_id)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_notification_dismissals")
    op.execute("DROP INDEX IF EXISTS idx_notifications_active")
    op.execute("DROP TABLE IF EXISTS notifications")

"""billing_events keeps its rows when the user is deleted

Revision ID: 0118
Revises: 0117
Create Date: 2026-09-29

Accounts can now be deleted from the account page (POST /auth/delete-account).
billing_events.user_id was NOT NULL with ON DELETE CASCADE, so deleting a paying
user would have erased their invoices: revenue totals would shrink after the
fact, and so would the partner accruals, which are computed from these rows
(each row carries its own referral_source snapshot, so the accrual does not
need the user). The payment record stays, unlinked from the person: user_id
becomes NULL.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0118"
down_revision: Union[str, None] = "0117"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The FK was declared inline in 0054, so its name is generated; look it up.
_DROP_USER_FK = """
    DO $$
    DECLARE fk text;
    BEGIN
        SELECT conname INTO fk FROM pg_constraint
        WHERE conrelid = 'billing_events'::regclass
          AND confrelid = 'users'::regclass
          AND contype = 'f';
        IF fk IS NOT NULL THEN
            EXECUTE 'ALTER TABLE billing_events DROP CONSTRAINT ' || quote_ident(fk);
        END IF;
    END $$;
"""


def upgrade() -> None:
    op.execute("ALTER TABLE billing_events ALTER COLUMN user_id DROP NOT NULL")
    op.execute(_DROP_USER_FK)
    op.execute(
        "ALTER TABLE billing_events ADD CONSTRAINT billing_events_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    # Rows already unlinked from a deleted user cannot go back under NOT NULL.
    op.execute("DELETE FROM billing_events WHERE user_id IS NULL")
    op.execute(_DROP_USER_FK)
    op.execute(
        "ALTER TABLE billing_events ADD CONSTRAINT billing_events_user_id_fkey "
        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE"
    )
    op.execute("ALTER TABLE billing_events ALTER COLUMN user_id SET NOT NULL")

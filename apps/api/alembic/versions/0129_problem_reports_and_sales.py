"""Problem reports and the sales role (2026-10-16).

- support_tickets gains a kind ('contact' from the Contact Us form, 'problem'
  from Report a problem), the page/browser context and screenshot of a problem
  report, admin notes, and the claim/resolve columns a laptop runner uses.
  Status adds 'working', 'done' and 'wont_fix'.
- users.is_sales / sales_code: a salesperson's admin-lite (/sales), keyed to
  their pilot code (Jordan Hall: 'jordan').
- sales_leads: a salesperson's lead tracker, imported from the outreach list.

Revision ID: 0129
Revises: 0128
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0129"
down_revision: Union[str, None] = "0128"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE support_tickets
            ADD COLUMN kind            TEXT NOT NULL DEFAULT 'contact',
            ADD COLUMN context         JSONB,
            ADD COLUMN screenshot_path TEXT,
            ADD COLUMN admin_notes     TEXT,
            ADD COLUMN claimed_by      TEXT,
            ADD COLUMN claimed_at      TIMESTAMPTZ,
            ADD COLUMN resolved_at     TIMESTAMPTZ
        """
    )
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_status_check")
    op.execute(
        """
        ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_status_check
            CHECK (status IN ('open', 'replied', 'closed', 'working', 'done', 'wont_fix'))
        """
    )
    op.execute("ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_kind_check CHECK (kind IN ('contact', 'problem'))")
    op.execute("CREATE INDEX idx_support_tickets_kind_status ON support_tickets(kind, status, created_at)")

    op.execute(
        """
        ALTER TABLE users
            ADD COLUMN is_sales   BOOLEAN NOT NULL DEFAULT FALSE,
            ADD COLUMN sales_code TEXT
        """
    )
    op.execute("CREATE UNIQUE INDEX idx_users_sales_code ON users(sales_code) WHERE sales_code IS NOT NULL")

    op.execute(
        """
        CREATE TABLE sales_leads (
            id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            owner_user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            lead_ref       TEXT,
            source         TEXT NOT NULL DEFAULT 'manual',
            company        TEXT NOT NULL,
            dba            TEXT,
            city           TEXT,
            state          TEXT,
            phone          TEXT,
            website        TEXT,
            contact_name   TEXT,
            contact_role   TEXT,
            contact_email  TEXT,
            towboats       INTEGER,
            tugs           INTEGER,
            passenger      INTEGER,
            osv            INTEGER,
            service        TEXT,
            commodities    TEXT,
            area           TEXT,
            status         TEXT NOT NULL DEFAULT 'new'
                           CHECK (status IN ('new', 'contacted', 'demo', 'trial', 'paying', 'lost')),
            next_step      TEXT,
            next_step_at   DATE,
            notes          TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_sales_leads_owner ON sales_leads(owner_user_id, status, next_step_at)")
    op.execute("CREATE UNIQUE INDEX idx_sales_leads_ref ON sales_leads(owner_user_id, lead_ref) WHERE lead_ref IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sales_leads")
    op.execute("DROP INDEX IF EXISTS idx_users_sales_code")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_sales, DROP COLUMN IF EXISTS sales_code")
    op.execute("DROP INDEX IF EXISTS idx_support_tickets_kind_status")
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_kind_check")
    op.execute("ALTER TABLE support_tickets DROP CONSTRAINT IF EXISTS support_tickets_status_check")
    op.execute(
        "ALTER TABLE support_tickets ADD CONSTRAINT support_tickets_status_check "
        "CHECK (status IN ('open', 'replied', 'closed'))"
    )
    op.execute(
        """
        ALTER TABLE support_tickets
            DROP COLUMN IF EXISTS kind, DROP COLUMN IF EXISTS context, DROP COLUMN IF EXISTS screenshot_path,
            DROP COLUMN IF EXISTS admin_notes, DROP COLUMN IF EXISTS claimed_by, DROP COLUMN IF EXISTS claimed_at,
            DROP COLUMN IF EXISTS resolved_at
        """
    )

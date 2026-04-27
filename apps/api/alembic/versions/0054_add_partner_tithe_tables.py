"""add referral_partners + billing_events + partner_payouts tables

Revision ID: 0054
Revises: 0053
Create Date: 2026-04-27

Sprint D6.14 — partner tithe tracking.

  referral_partners — config row per attribution channel. Maps a
                      `users.referral_source` value to a display name +
                      tithe_pct. Editable in the future via admin UI.
                      Seeded with three rows to match the three live
                      landing pages (womenoffshore / captainkarynn /
                      atseastories), all at 10%.

  billing_events    — per-invoice ledger populated by the
                      stripe_service.handle_webhook_event 'invoice.paid'
                      branch. Carries amount_paid_cents, period_start,
                      period_end, and a denormalized referral_source
                      snapshot for fast partner aggregations.

  partner_payouts   — manual payout records. Admin marks "we sent
                      Women Offshore $X on Y date"; outstanding balance
                      = sum(tithe_owed) - sum(amount_paid).

All three are independent of the existing schema and don't migrate any
historical data — billing_events fills going forward via the existing
webhook; the manual payout ledger starts empty.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── referral_partners ───────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS referral_partners (
            referral_source TEXT PRIMARY KEY,
            partner_name    TEXT NOT NULL,
            tithe_pct       NUMERIC(5,2) NOT NULL DEFAULT 10.00,
            payout_method   TEXT,
            payout_contact  TEXT,
            notes           TEXT,
            active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Seed the three current channels. captainkarynn defaults to "Women
    # Offshore" per Blake's note — "/captainkarynn still does our
    # generic 10% distribution to our partners" — interpreted as the
    # default charity destination. Easy to edit later via UPDATE.
    op.execute(
        """
        INSERT INTO referral_partners (referral_source, partner_name, tithe_pct, notes)
        VALUES
            ('womenoffshore',  'Women Offshore', 10.00,
             'Charity partner per /womenoffshore page copy. 10% of every subscription that originates from /womenoffshore.'),
            ('captainkarynn',  'Women Offshore', 10.00,
             'Generic partner distribution for /captainkarynn promo signups. Defaults to Women Offshore charity; edit partner_name to redirect.'),
            ('atseastories',   '@atseastories',  10.00,
             'Private service agreement with @atseastories Instagram channel operator. NOT advertised on /ass page. 10% commission on subscriptions originating from /ass.')
        ON CONFLICT (referral_source) DO NOTHING
        """
    )

    # ── billing_events ──────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_events (
            id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id                  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            stripe_invoice_id        TEXT NOT NULL UNIQUE,
            stripe_subscription_id   TEXT,
            stripe_customer_id       TEXT,
            -- amount_paid_cents is what Stripe actually collected
            -- (i.e., post-discount, pre-fees). amount_total_cents is
            -- the invoice total in case the two diverge.
            amount_paid_cents        INTEGER NOT NULL,
            amount_total_cents       INTEGER NOT NULL,
            currency                 TEXT NOT NULL DEFAULT 'usd',
            -- The billing period this invoice covers.
            period_start             TIMESTAMPTZ,
            period_end               TIMESTAMPTZ,
            paid_at                  TIMESTAMPTZ NOT NULL,
            -- Denormalized so partner-tithe aggregations don't have to
            -- join users on every query. Captures the user's attribution
            -- AT THE TIME OF PAYMENT — if a user later changes their
            -- referral_source (admin override), historical events are
            -- unaffected. Nullable: most users have no referral_source.
            referral_source          TEXT,
            -- Snapshot of the user's tier at payment time.
            subscription_tier        TEXT,
            billing_interval         TEXT,
            created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_billing_events_paid_at "
        "ON billing_events (paid_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_billing_events_referral_source "
        "ON billing_events (referral_source) WHERE referral_source IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_billing_events_user_id "
        "ON billing_events (user_id)"
    )

    # ── partner_payouts ─────────────────────────────────────────────────
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS partner_payouts (
            id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            referral_source     TEXT NOT NULL REFERENCES referral_partners(referral_source),
            -- Snapshot of partner_name at the time of payout — protects
            -- the historical record if the partner's display name is
            -- later edited in referral_partners.
            partner_name_at_time TEXT NOT NULL,
            amount_cents        INTEGER NOT NULL,
            currency            TEXT NOT NULL DEFAULT 'usd',
            paid_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            -- Free-text receipt: e.g., "Wire ref WO-2026-04 for April
            -- accruals" or "Venmo @atseastories $4.50 May 1 2026".
            notes               TEXT,
            -- Which admin recorded this payout.
            created_by_user_id  UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_partner_payouts_referral_source "
        "ON partner_payouts (referral_source, paid_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS partner_payouts")
    op.execute("DROP TABLE IF EXISTS billing_events")
    op.execute("DROP TABLE IF EXISTS referral_partners")

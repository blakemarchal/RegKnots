"""redesign tithe distribution: split partners + rules; add default pool

Revision ID: 0055
Revises: 0054
Create Date: 2026-04-27

Sprint D6.14b — corrects the tithe model.

The 0054 schema treated each referral_source as routing to a single
partner. That's right for /womenoffshore (→ Women Offshore) and /ass
(→ @atseastories), but wrong for /captainkarynn and any unattributed
revenue. Per Karynn's policy: all revenue NOT from /womenoffshore or
/ass is treated generically — 10% split equally across the "Giving
Back" charity partners (currently Mercy Ships, Waves of Impact,
Elijah Rising; Women Offshore is excluded since she has her own
dedicated funnel).

New model:
  tithe_partners — named beneficiaries (one row per real-world entity).
  tithe_rules    — distribution rules: maps a referral_source (or NULL
                   for the default catch-all) to one or more partners
                   with relative weights. Multiple rows per
                   referral_source = multi-partner split. NULL
                   referral_source = applies to any revenue not matched
                   by an explicit rule.
  partner_payouts now FKs to tithe_partners.id.

Rebuild is destructive (DROP + CREATE) since the 0054 tables were
seeded ~30 min ago with ZERO downstream data: no billing_events have
fired their webhook yet, no payouts recorded. Safe to wipe.

billing_events is preserved as-is; its referral_source column still
captures the channel snapshot at payment time.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0055"
down_revision: Union[str, None] = "0054"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the 0054 tables — no real data, just seed config.
    op.execute("DROP TABLE IF EXISTS partner_payouts CASCADE")
    op.execute("DROP TABLE IF EXISTS referral_partners CASCADE")

    # ── tithe_partners: named beneficiaries ──────────────────────────────
    op.execute(
        """
        CREATE TABLE tithe_partners (
            id              SERIAL PRIMARY KEY,
            name            TEXT NOT NULL UNIQUE,
            payout_method   TEXT,
            payout_contact  TEXT,
            notes           TEXT,
            active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

    # ── tithe_rules: routing config ──────────────────────────────────────
    # NULL referral_source = catch-all default rule (applies to any
    # revenue not matched by an explicit non-NULL rule).
    # Multiple rows per (referral_source) = multi-partner pool with
    # weighted distribution: partner_share = total_pool × weight / sum(weights).
    op.execute(
        """
        CREATE TABLE tithe_rules (
            id               SERIAL PRIMARY KEY,
            referral_source  TEXT,
            partner_id       INTEGER NOT NULL REFERENCES tithe_partners(id) ON DELETE CASCADE,
            weight           INTEGER NOT NULL DEFAULT 1 CHECK (weight > 0),
            tithe_pct        NUMERIC(5,2) NOT NULL DEFAULT 10.00 CHECK (tithe_pct >= 0),
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    # Composite uniqueness: at most one (referral_source, partner) row.
    # COALESCE handles NULL referral_source (postgres treats NULLs as
    # distinct in standard UNIQUE constraints).
    op.execute(
        """
        CREATE UNIQUE INDEX idx_tithe_rules_unique
        ON tithe_rules (COALESCE(referral_source, '__default__'), partner_id)
        """
    )
    op.execute(
        "CREATE INDEX idx_tithe_rules_referral_source ON tithe_rules (referral_source)"
    )

    # ── partner_payouts: manual payout ledger ────────────────────────────
    op.execute(
        """
        CREATE TABLE partner_payouts (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            partner_id           INTEGER NOT NULL REFERENCES tithe_partners(id),
            partner_name_at_time TEXT NOT NULL,
            amount_cents         INTEGER NOT NULL CHECK (amount_cents > 0),
            currency             TEXT NOT NULL DEFAULT 'usd',
            paid_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes                TEXT,
            created_by_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE INDEX idx_partner_payouts_partner_paid
        ON partner_payouts (partner_id, paid_at DESC)
        """
    )

    # ── Seeds ────────────────────────────────────────────────────────────
    # Five partners — direct beneficiaries first, then default-pool ones.
    op.execute(
        """
        INSERT INTO tithe_partners (name, notes) VALUES
            ('Women Offshore',
             'Charity. Direct funnel from /womenoffshore — 10% of those subscriptions. Not in the default pool (excluded since she has her own dedicated funnel; revisit if Karynn wants both).'),
            ('@atseastories',
             'Private service agreement. Direct funnel from /ass — 10% of those subscriptions. NOT advertised on the page.'),
            ('Mercy Ships',
             'Default Giving Back charity. Receives 1/3 of the 10% generic-pool tithe.'),
            ('Waves of Impact',
             'Default Giving Back charity. Receives 1/3 of the 10% generic-pool tithe.'),
            ('Elijah Rising',
             'Default Giving Back charity. Receives 1/3 of the 10% generic-pool tithe.')
        """
    )

    # Direct rules — each routes 100% of its bucket to one partner.
    op.execute(
        """
        INSERT INTO tithe_rules (referral_source, partner_id, weight, tithe_pct)
        SELECT 'womenoffshore', id, 1, 10.00 FROM tithe_partners WHERE name = 'Women Offshore';
        """
    )
    op.execute(
        """
        INSERT INTO tithe_rules (referral_source, partner_id, weight, tithe_pct)
        SELECT 'atseastories', id, 1, 10.00 FROM tithe_partners WHERE name = '@atseastories';
        """
    )

    # Default-pool rules — NULL referral_source. Three rows, equal
    # weight, splits the 10% three ways. Catches: NULL referral_source,
    # 'captainkarynn', and any future channel without a dedicated rule.
    op.execute(
        """
        INSERT INTO tithe_rules (referral_source, partner_id, weight, tithe_pct)
        SELECT NULL, id, 1, 10.00 FROM tithe_partners WHERE name = 'Mercy Ships';
        """
    )
    op.execute(
        """
        INSERT INTO tithe_rules (referral_source, partner_id, weight, tithe_pct)
        SELECT NULL, id, 1, 10.00 FROM tithe_partners WHERE name = 'Waves of Impact';
        """
    )
    op.execute(
        """
        INSERT INTO tithe_rules (referral_source, partner_id, weight, tithe_pct)
        SELECT NULL, id, 1, 10.00 FROM tithe_partners WHERE name = 'Elijah Rising';
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS partner_payouts CASCADE")
    op.execute("DROP TABLE IF EXISTS tithe_rules CASCADE")
    op.execute("DROP TABLE IF EXISTS tithe_partners CASCADE")
    # Recreate the 0054 tables at their seed state so downgrade is reversible.
    op.execute(
        """
        CREATE TABLE referral_partners (
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
    op.execute(
        """
        CREATE TABLE partner_payouts (
            id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            referral_source      TEXT NOT NULL REFERENCES referral_partners(referral_source),
            partner_name_at_time TEXT NOT NULL,
            amount_cents         INTEGER NOT NULL,
            currency             TEXT NOT NULL DEFAULT 'usd',
            paid_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notes                TEXT,
            created_by_user_id   UUID REFERENCES users(id) ON DELETE SET NULL,
            created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )

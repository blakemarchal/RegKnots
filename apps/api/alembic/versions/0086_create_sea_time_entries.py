"""create sea_time_entries table

Revision ID: 0086
Revises: 0085
Create Date: 2026-05-05

D6.62 — sea-time logger (Sprint 2 of MarinerDocs competitive response).

Each row is a BLOCK of consecutive sea time, not per-day. A typical
mariner logs trips/voyages/contracts as discrete blocks ("Master on
M/V Jane Doe, Inland, 2026-03-01 → 2026-04-15 = 46 days") and the
USCG Statement of Sea Service is calculated from those blocks.
Per-day granularity would be exhausting to enter and would not match
the regulatory output format.

The schema is intentionally close to `sea_service.VesselEntry` so the
existing letter generator can pull entries directly into the prefill.

Vessel data is denormalized — `vessel_id` is an optional FK back to
the user's vessels table, but vessel_name + tonnage + tunnage etc. are
stored on the row so deleting a vessel record (or sailing on someone
else's boat that was never added to the user's vessel list) doesn't
strand history.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0086"
down_revision: Union[str, None] = "0085"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE sea_time_entries (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            vessel_id       UUID REFERENCES vessels(id) ON DELETE SET NULL,

            -- Vessel snapshot (denormalized; survives vessel deletion)
            vessel_name     TEXT NOT NULL,
            official_number TEXT,
            vessel_type     TEXT,
            gross_tonnage   NUMERIC(12,2),
            horsepower      TEXT,
            propulsion      TEXT,
            route_type      TEXT,

            -- Service details — what the mariner served as, on what dates
            capacity_served TEXT NOT NULL,
            from_date       DATE NOT NULL,
            to_date         DATE NOT NULL,
            days_on_board   INTEGER NOT NULL,

            -- Employer + audit notes
            employer_name   TEXT,
            employer_signed BOOLEAN NOT NULL DEFAULT FALSE,
            notes           TEXT,

            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

            CONSTRAINT sea_time_entries_dates_chk CHECK (to_date >= from_date),
            CONSTRAINT sea_time_entries_days_chk  CHECK (days_on_board >= 0)
        )
    """)
    op.execute(
        "CREATE INDEX idx_sea_time_entries_user "
        "ON sea_time_entries(user_id, from_date DESC)"
    )
    op.execute(
        "CREATE INDEX idx_sea_time_entries_vessel "
        "ON sea_time_entries(vessel_id) WHERE vessel_id IS NOT NULL"
    )
    op.execute("""
        CREATE TRIGGER sea_time_entries_updated_at
            BEFORE UPDATE ON sea_time_entries
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
    """)


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS sea_time_entries_updated_at ON sea_time_entries"
    )
    op.execute("DROP TABLE IF EXISTS sea_time_entries")

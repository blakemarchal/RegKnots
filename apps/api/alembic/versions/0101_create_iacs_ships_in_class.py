"""create iacs_ships_in_class lookup table

Revision ID: 0101
Revises: 0100
Create Date: 2026-05-16

D6.94 Sprint A — IMO → class society lookup table.

IACS publishes a public weekly CSV at iacs.org.uk/membership/vessels-in-class
aggregating per-IMO class data from its 11 member societies (ABS, LR,
DNV, ClassNK, BV, KR, CCS, RINA, CRS, IRS, PRS). The 2026-05-15 file
held 86,688 rows / 61,127 distinct IMOs covering ~95% of merchant
tonnage globally — well above what RegKnots' user base will ever ask
about.

This table is the local cache. ``scripts/refresh_iacs_ships_in_class.py``
fetches + parses the CSV and upserts rows here on a weekly cadence
(wired into regknots-refresh-weekly.service). Auth-free, ToS-clean
(IACS aggregates data members already share publicly via Equasis;
the IACS-hosted CSV is not the Equasis dataset itself, so the IHS
commercial-use clause that gates Equasis does not apply).

The vessels POST/PATCH path consults this table when the user enters
an IMO without picking a society — auto-fills classification_society
with source='iacs_lookup' so the UI can hint "auto-populated, please
verify". On a no-match the column stays NULL and the UI prompts the
user to pick.

We store the upstream values verbatim (society codes like 'LRS' /
'NV' / 'NKK') plus a normalized society code in `society_normalized`
that maps to the vessels.classification_society enum. Pre-normalizing
makes lookup queries trivially fast and avoids re-mapping the 86k
rows on every read.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0101"
down_revision: Union[str, None] = "0100"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE iacs_ships_in_class (
            imo bigint PRIMARY KEY,
            society_raw text NOT NULL,
            society_normalized text,
            ship_name text,
            date_of_survey date,
            date_of_next_survey date,
            date_of_latest_status date,
            status text,
            status_reason text,
            snapshot_source_file text,
            refreshed_at timestamptz NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_iacs_society_normalized ON iacs_ships_in_class(society_normalized)")
    op.execute("CREATE INDEX idx_iacs_refreshed_at ON iacs_ships_in_class(refreshed_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS iacs_ships_in_class")

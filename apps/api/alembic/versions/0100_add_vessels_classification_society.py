"""add classification_society to vessels

Revision ID: 0100
Revises: 0099
Create Date: 2026-05-16

D6.94 Sprint A — vessel-profile classification society.

Class society membership is per-vessel, not per-flag. An ABS-classed
Liberian-flag tanker is bound by ABS rules; an LR-classed Marshallese
bulker by Lloyd's. The synthesizer needs this signal to route
class-society retrieval correctly (today the chat surfaces ABS, LR,
and DNV chunks indiscriminately when a class-relevant question fires).

Two columns added:

  * ``classification_society`` — the society code, NULL when unknown.
    Constrained to the 11 IACS member abbreviations plus 'other' and
    'unclassed'. Nullable so existing vessels don't get a forced value
    on migration; the value is set later by either user input or the
    iacs_ships_in_class auto-lookup (migration 0101).

  * ``classification_society_source`` — provenance tag, 'user' when
    the user picked it explicitly or 'iacs_lookup' when the auto-
    populate path filled it from the IACS Vessels-in-Class CSV. The
    UI distinguishes auto-populated values so users can verify /
    correct. NULL when the column itself is NULL.

The synthesizer reads ``classification_society`` via the vessel
profile context block (rag/user_context.py D6.94 patch) and uses it
to flag the binding class-society rules vs. cross-reference ones.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0100"
down_revision: Union[str, None] = "0099"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ALLOWED = [
    "ABS", "LR", "DNV", "ClassNK", "BV", "KR", "CCS",
    "RINA", "CRS", "IRS", "PRS",
    "other", "unclassed",
]


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vessels "
        "ADD COLUMN classification_society text, "
        "ADD COLUMN classification_society_source text"
    )
    values_sql = ", ".join(f"'{v}'" for v in _ALLOWED)
    op.execute(
        "ALTER TABLE vessels "
        "ADD CONSTRAINT vessels_classification_society_check "
        f"CHECK (classification_society IS NULL OR classification_society IN ({values_sql}))"
    )
    op.execute(
        "ALTER TABLE vessels "
        "ADD CONSTRAINT vessels_classification_society_source_check "
        "CHECK (classification_society_source IS NULL OR "
        "classification_society_source IN ('user', 'iacs_lookup'))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE vessels "
        "DROP CONSTRAINT IF EXISTS vessels_classification_society_source_check, "
        "DROP CONSTRAINT IF EXISTS vessels_classification_society_check, "
        "DROP COLUMN IF EXISTS classification_society_source, "
        "DROP COLUMN IF EXISTS classification_society"
    )

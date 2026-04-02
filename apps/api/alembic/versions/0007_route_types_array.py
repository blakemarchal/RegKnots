"""migrate route_type TEXT to route_types TEXT[]

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-02

Converts the single-value route_type column to a route_types TEXT[] array
so vessels can have multiple route classifications.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Step 1: Add new array column (nullable initially)
    op.execute(sa.text("ALTER TABLE vessels ADD COLUMN route_types TEXT[]"))

    # Step 2: Migrate existing data from route_type into route_types
    op.execute(sa.text("UPDATE vessels SET route_types = ARRAY[route_type]"))

    # Step 3: Set NOT NULL constraint now that all rows have data
    op.execute(sa.text("ALTER TABLE vessels ALTER COLUMN route_types SET NOT NULL"))

    # Step 4: Drop the old route_type column (and its CHECK constraint)
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN route_type"))


def downgrade() -> None:
    # Reverse: re-add route_type, populate from first element, drop route_types
    op.execute(sa.text(
        "ALTER TABLE vessels ADD COLUMN route_type TEXT"
    ))
    op.execute(sa.text(
        "UPDATE vessels SET route_type = route_types[1]"
    ))
    op.execute(sa.text(
        "ALTER TABLE vessels ALTER COLUMN route_type SET NOT NULL"
    ))
    op.execute(sa.text(
        "ALTER TABLE vessels ADD CONSTRAINT vessels_route_type_check "
        "CHECK (route_type IN ('inland', 'coastal', 'international'))"
    ))
    op.execute(sa.text("ALTER TABLE vessels DROP COLUMN route_types"))

"""expand user_credentials.credential_type allow-list

Revision ID: 0087
Revises: 0086
Create Date: 2026-05-06

D6.67 — Karynn vetting feedback: the original 5 types (mmc / stcw /
medical / twic / other) covered the maritime-specific core but
forced everything else into 'other':

  - passport / passport card  (universal travel doc, easy non-sailor
                                test for the OCR scanner)
  - GMDSS operator certificate (Global Maritime Distress & Safety)
  - DP certificate            (Dynamic Positioning operator)
  - drug test letter          (DOT 5-panel, required for MMC issue)
  - vaccine record            (yellow fever card, COVID, etc.)
  - sea service letter        (signed discharge — distinct format)
  - course certificate        (BST, AFF, Radar Observer, etc.)

Expanding the enum lets the scanner classify the document precisely
(see _CREDENTIAL_EXTRACTION_PROMPT in credentials.py) and gives the
Renewal Co-Pilot specific anchors per type.

The new values are additive — existing 'other' rows are untouched.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "0087"
down_revision: Union[str, None] = "0086"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_NEW_TYPES = (
    'mmc', 'stcw', 'medical', 'twic',
    'passport', 'passport_card',
    'gmdss', 'dp',
    'drug_test', 'vaccine',
    'sea_service', 'course_cert',
    'other',
)
_OLD_TYPES = ('mmc', 'stcw', 'medical', 'twic', 'other')


def upgrade() -> None:
    op.execute(
        "ALTER TABLE user_credentials "
        "DROP CONSTRAINT IF EXISTS user_credentials_credential_type_check"
    )
    types_sql = ", ".join(f"'{t}'" for t in _NEW_TYPES)
    op.execute(
        f"ALTER TABLE user_credentials "
        f"ADD CONSTRAINT user_credentials_credential_type_check "
        f"CHECK (credential_type IN ({types_sql}))"
    )


def downgrade() -> None:
    # Map any new-type rows back to 'other' before re-tightening the
    # constraint, otherwise the downgrade would fail on existing data.
    new_only = tuple(t for t in _NEW_TYPES if t not in _OLD_TYPES)
    if new_only:
        in_clause = ", ".join(f"'{t}'" for t in new_only)
        op.execute(
            f"UPDATE user_credentials SET credential_type = 'other' "
            f"WHERE credential_type IN ({in_clause})"
        )
    op.execute(
        "ALTER TABLE user_credentials "
        "DROP CONSTRAINT IF EXISTS user_credentials_credential_type_check"
    )
    old_sql = ", ".join(f"'{t}'" for t in _OLD_TYPES)
    op.execute(
        f"ALTER TABLE user_credentials "
        f"ADD CONSTRAINT user_credentials_credential_type_check "
        f"CHECK (credential_type IN ({old_sql}))"
    )

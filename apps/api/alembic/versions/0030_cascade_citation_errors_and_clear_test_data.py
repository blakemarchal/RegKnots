"""cascade citation_errors.conversation_id + clear test pilot/support data

Revision ID: 0030
Revises: 0029
Create Date: 2026-04-08

- Drop and recreate citation_errors_conversation_id_fkey with ON DELETE CASCADE
  so deleting a user (which cascades to conversations) no longer fails on the
  citation_errors FK. This was the only FK to users(id) or conversations(id)
  still using NO ACTION; everything else already cascades.
- Clear pilot_survey_responses and support_tickets — both contained only
  internal test data prior to launch.
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE citation_errors "
        "DROP CONSTRAINT IF EXISTS citation_errors_conversation_id_fkey"
    )
    op.execute(
        "ALTER TABLE citation_errors "
        "ADD CONSTRAINT citation_errors_conversation_id_fkey "
        "FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE"
    )

    # Clear pre-launch test data
    op.execute("DELETE FROM pilot_survey_responses")
    op.execute("DELETE FROM support_tickets")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE citation_errors "
        "DROP CONSTRAINT IF EXISTS citation_errors_conversation_id_fkey"
    )
    op.execute(
        "ALTER TABLE citation_errors "
        "ADD CONSTRAINT citation_errors_conversation_id_fkey "
        "FOREIGN KEY (conversation_id) REFERENCES conversations(id)"
    )

"""fix users_role_check to allow D6.81 persona values

Revision ID: 0094
Revises: 0093
Create Date: 2026-05-10

CRITICAL HOTFIX — every signup since Sprint D6.81 has been failing
with a 500 because the frontend register page defaults to role
'mariner_shipboard' (and the API's _VALID_ROLES accepts it), but the
DB check constraint `users_role_check` was never migrated past the
legacy job-title set.

Old constraint allowed: captain, mate, engineer, chief_engineer, other
Frontend / API send:    mariner_shipboard, cadet_student, teacher_instructor,
                        shore_side_compliance, legal_consultant (+ legacy)

Capt Hall (capthallmma18@gmail.com) reported "registration failed" on
2026-05-10 ~15:17 UTC. Forensic confirmed via journalctl: every POST
/auth/register returns 500 with CheckViolationError on `users_role_check`.

This migration drops the legacy constraint and recreates it with the
full persona-aware set from app.routers.auth._VALID_ROLES (the source
of truth at the application layer). Both sets are listed so legacy
rows continue to pass validation when their record is touched.

No data backfill required — failed register attempts roll back; no
orphan rows.
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0094"
down_revision: Union[str, None] = "0093"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (
            role = ANY (ARRAY[
                -- Legacy maritime job titles (kept for backward compat with
                -- pre-D6.81 rows; new signups don't use these).
                'captain'::text,
                'mate'::text,
                'engineer'::text,
                'chief_engineer'::text,
                'other'::text,
                -- Sprint D6.81+ unified persona values. Mirrors
                -- _VALID_ROLES in apps/api/app/routers/auth.py and
                -- PERSONA_OPTIONS in apps/web/src/lib/personaOptions.ts.
                -- If you add a persona there, add it here too.
                'mariner_shipboard'::text,
                'cadet_student'::text,
                'teacher_instructor'::text,
                'shore_side_compliance'::text,
                'legal_consultant'::text
            ])
        )
        """
    )


def downgrade() -> None:
    # Reverting would re-break signups; only run this if you also
    # downgrade the application code. Recreates the legacy-only set.
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute(
        """
        ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (
            role = ANY (ARRAY[
                'captain'::text, 'mate'::text, 'engineer'::text,
                'chief_engineer'::text, 'other'::text
            ])
        )
        """
    )

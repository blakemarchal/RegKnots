"""Seed, or reset, the Wheelhouse demo workspace (growth plan step 4, 2026-10-14).

A fictional towing company for demos and pilot calls: "Gulf Coast Marine
Towing (Demo)" with the M/V Bay Pioneer, four fictional crewmembers with
credentials (one expired, some expiring soon, so Fleet Audit Readiness has
real findings), sea time, a watch handoff note and an excerpt of a TSMS as a
company document. Blake owns it and Karynn is an admin, so either can demo it
from their own account; the crew are internal accounts on
@demo.regknots.invalid addresses that cannot sign in.

Run on the VPS from apps/api (reads the prod .env; the TSMS is embedded with
the OpenAI key, a fraction of a cent):

  uv run python ../../scripts/demo/seed_demo_workspace.py           # create if missing
  uv run python ../../scripts/demo/seed_demo_workspace.py --reset   # delete everything and recreate

--reset deletes the workspace's conversations too, so a demo starts clean.
"""
from __future__ import annotations

import asyncio
import json
import secrets
import shutil
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "apps" / "api"))

from app.auth.service import hash_password  # noqa: E402
from app.config import settings  # noqa: E402

WORKSPACE_ID = uuid.UUID("d6d63d63-3333-4303-8003-000000000001")
WORKSPACE_NAME = "Gulf Coast Marine Towing (Demo)"
VESSEL_NAME = "M/V Bay Pioneer"
OWNER_EMAIL = "blakemarchal@gmail.com"
ADMIN_EMAILS = ["kdmarchal@gmail.com"]
CREW_DOMAIN = "demo.regknots.invalid"
TSMS_FILE = Path(__file__).with_name("demo_tsms.txt")
_NO_EMAIL = '{"cert_expiry_reminders": false, "reg_change_digest": false, "reg_digest_frequency": "weekly"}'

TODAY = date.today()


def d(days: int) -> date:
    return TODAY + timedelta(days=days)


# Fictional crew. Expiry offsets are days from today, so the findings stay
# current whenever the demo is reset.
CREW = [
    {
        "email": f"dale.fontenot@{CREW_DOMAIN}", "name": "Dale Fontenot", "role": "captain",
        "capacity": "Master of Towing Vessels",
        "credentials": [
            ("mmc", "MMC: Master of Towing Vessels, Near Coastal", 1400, 260),
            ("medical", "Medical Certificate (National)", 690, 40),
            ("twic", "TWIC", 1500, 310),
            ("drug_test", "Random drug test (DOT)", -95, None),
        ],
        "sea_time": [(-420, -330), (-300, -210), (-150, -60)],
    },
    {
        "email": f"rosa.alvarez@{CREW_DOMAIN}", "name": "Rosa Alvarez", "role": "mate",
        "capacity": "Mate (Pilot) of Towing Vessels",
        "credentials": [
            ("mmc", "MMC: Mate (Pilot) of Towing Vessels, Western Rivers and Near Coastal", 700, 1120),
            ("medical", "Medical Certificate (National)", 400, 330),
            ("twic", "TWIC", 1805, -20),
        ],
        "sea_time": [(-380, -290), (-260, -170), (-120, -30)],
    },
    {
        "email": f"marcus.lee@{CREW_DOMAIN}", "name": "Marcus Lee", "role": "engineer",
        "capacity": "Engineer",
        "credentials": [
            ("mmc", "MMC: QMED (Oiler)", 900, 920),
            ("medical", "Medical Certificate (National)", 600, 130),
            ("course_cert", "Basic Firefighting", 1000, None),
        ],
        "sea_time": [(-200, -110), (-90, -10)],
    },
    {
        "email": f"jamie.thibodeaux@{CREW_DOMAIN}", "name": "Jamie Thibodeaux", "role": "mariner_shipboard",
        "capacity": "Deckhand",
        "credentials": [
            ("twic", "TWIC", 300, 1525),
            ("course_cert", "Basic Safety Training (STCW)", 250, 1575),
            ("drug_test", "Pre-employment drug test (DOT)", -260, None),
        ],
        "sea_time": [(-240, -150), (-100, -20)],
    },
]

HANDOFF = (
    "Watch handoff, 0600: Pushing 4 loads of fertilizer northbound, ICW mile 280. Port raw-water pump packing "
    "weeping, checked every 2 hours, spare packing in the engine room locker. Fuel 62%. Next crew change Thursday "
    "at Port Arthur. Towline end-for-ended on the 3rd, logged."
)


async def reset(pool) -> None:
    await pool.execute("DELETE FROM conversations WHERE workspace_id = $1", WORKSPACE_ID)
    await pool.execute("DELETE FROM workspaces WHERE id = $1", WORKSPACE_ID)   # members, vessel, docs cascade
    await pool.execute("DELETE FROM users WHERE email LIKE $1", f"%@{CREW_DOMAIN}")
    shutil.rmtree(Path(settings.upload_dir) / "workspace_docs" / str(WORKSPACE_ID), ignore_errors=True)
    print("demo workspace removed")


async def seed(pool) -> None:
    owner = await pool.fetchval("SELECT id FROM users WHERE email = $1", OWNER_EMAIL)
    if owner is None:
        raise SystemExit(f"owner {OWNER_EMAIL} not found")
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                """INSERT INTO workspaces (id, name, owner_user_id, status, seat_cap, internal_only, handoff_note,
                                           handoff_note_updated_at, handoff_note_updated_by_user_id)
                   VALUES ($1, $2, $3, 'active', 10, TRUE, $4, now(), $3)""",
                WORKSPACE_ID, WORKSPACE_NAME, owner, HANDOFF,
            )
            await conn.execute(
                "INSERT INTO workspace_members (workspace_id, user_id, role) VALUES ($1, $2, 'owner')",
                WORKSPACE_ID, owner)
            for email in ADMIN_EMAILS:
                uid = await conn.fetchval("SELECT id FROM users WHERE email = $1", email)
                if uid:
                    await conn.execute(
                        "INSERT INTO workspace_members (workspace_id, user_id, role, invited_by_user_id) "
                        "VALUES ($1, $2, 'admin', $3)", WORKSPACE_ID, uid, owner)
            vessel = await conn.fetchval(
                """INSERT INTO vessels (user_id, workspace_id, name, vessel_type, gross_tonnage, flag_state,
                                        route_types, cargo_types, subchapter, inspection_certificate_type,
                                        manning_requirement, route_limitations)
                   VALUES ($1, $2, $3, 'Towing / Tugboat', 99, 'United States', ARRAY['inland','coastal'],
                           ARRAY['dry bulk barges'], 'M', 'Certificate of Inspection (Subchapter M)',
                           'Master of Towing Vessels, Mate (Pilot) of Towing Vessels, 2 deckhands',
                           'Lakes, bays and sounds; limited coastwise, Gulf of Mexico within 20 nm of shore')
                   RETURNING id""",
                owner, WORKSPACE_ID, VESSEL_NAME,
            )
            for person in CREW:
                uid = await conn.fetchval(
                    """INSERT INTO users (email, hashed_password, full_name, role, trial_ends_at, email_verified,
                                          is_internal, notification_preferences, onboarding_completed_at)
                       VALUES ($1, $2, $3, $4, now(), TRUE, TRUE, $5::jsonb, now()) RETURNING id""",
                    person["email"], hash_password(secrets.token_urlsafe(48)), person["name"], person["role"],
                    _NO_EMAIL,
                )
                await conn.execute(
                    "INSERT INTO workspace_members (workspace_id, user_id, role, invited_by_user_id) "
                    "VALUES ($1, $2, 'member', $3)", WORKSPACE_ID, uid, owner)
                for i, (ctype, title, issued_ago, expires_in) in enumerate(person["credentials"]):
                    await conn.execute(
                        """INSERT INTO user_credentials (user_id, credential_type, title, credential_number,
                                                         issuing_authority, issue_date, expiry_date, notes)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, 'Demo record')""",
                        uid, ctype, title, f"DEMO-{person['name'].split()[1][:4].upper()}-{i + 1}",
                        "U.S. Coast Guard" if ctype in ("mmc", "medical") else (
                            "TSA" if ctype == "twic" else "Gulf Coast Marine Towing"),
                        d(-abs(issued_ago)), d(expires_in) if expires_in is not None else None,
                    )
                for start, end in person["sea_time"]:
                    await conn.execute(
                        """INSERT INTO sea_time_entries (user_id, vessel_id, vessel_name, vessel_type, gross_tonnage,
                                                         route_type, capacity_served, from_date, to_date,
                                                         days_on_board, employer_name, employer_signed)
                           VALUES ($1, $2, $3, 'Towing / Tugboat', 99, 'Near Coastal', $4, $5, $6, $7,
                                   'Gulf Coast Marine Towing (Demo)', TRUE)""",
                        uid, vessel, VESSEL_NAME, person["capacity"], d(start), d(end), end - start + 1,
                    )

    # The TSMS excerpt as a company document, processed like an upload.
    from app import company_docs
    doc_id = uuid.uuid4()
    directory = Path(settings.upload_dir) / "workspace_docs" / str(WORKSPACE_ID)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{doc_id}.txt"
    shutil.copyfile(TSMS_FILE, path)
    await pool.execute(
        """INSERT INTO workspace_documents (id, workspace_id, uploaded_by, filename, title, mime_type, file_path,
                                            size_bytes)
           VALUES ($1, $2, $3, 'Gulf Coast Marine Towing TSMS (excerpts).txt',
                   'Gulf Coast Marine Towing TSMS (excerpts)', 'text/plain', $4, $5)""",
        doc_id, WORKSPACE_ID, owner, str(path), path.stat().st_size,
    )
    await company_docs.process_document(pool, doc_id, settings.openai_api_key)
    status = await pool.fetchrow("SELECT status, chunk_count, error FROM workspace_documents WHERE id = $1", doc_id)
    print(json.dumps({"workspace": str(WORKSPACE_ID), "vessel": str(vessel), "crew": len(CREW),
                      "tsms": dict(status)}, default=str))


async def main(argv: list[str]) -> None:
    import asyncpg
    pool = await asyncpg.create_pool(settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
                                     min_size=1, max_size=2)
    try:
        exists = await pool.fetchval("SELECT 1 FROM workspaces WHERE id = $1", WORKSPACE_ID)
        if "--reset" in argv:
            await reset(pool)
        elif exists:
            print("demo workspace already exists (use --reset to recreate)")
            return
        await seed(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))

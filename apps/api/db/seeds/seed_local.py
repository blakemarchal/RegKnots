"""
Local development seed script.

Usage (from apps/api/):
    uv run python db/seeds/seed_local.py
"""
import asyncio
import sys
from pathlib import Path
from uuid import UUID

import asyncpg

# Make `app` importable
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.auth.service import hash_password  # noqa: E402
from app.config import settings             # noqa: E402

SEED_EMAIL = "captain@regknots.dev"
SEED_PASSWORD = "RegKnots2026!"


async def seed() -> None:
    pool = await asyncpg.create_pool(settings.database_url, min_size=1, max_size=2)

    print("Seeding users…")
    user_id: UUID | None = await pool.fetchval(
        "SELECT id FROM users WHERE email = $1", SEED_EMAIL
    )

    if user_id is None:
        user_id = await pool.fetchval(
            """
            INSERT INTO users (email, hashed_password, full_name, role, subscription_tier)
            VALUES ($1, $2, 'Dev Captain', 'captain', 'solo')
            RETURNING id
            """,
            SEED_EMAIL,
            hash_password(SEED_PASSWORD),
        )
        print(f"  Created user {SEED_EMAIL}  (id={user_id})")
    else:
        print(f"  User {SEED_EMAIL} already exists — skipped")

    print("Seeding vessels…")
    existing_vessel = await pool.fetchval(
        "SELECT id FROM vessels WHERE user_id = $1 AND name = 'MV RegKnots Demo'",
        user_id,
    )

    if existing_vessel is None:
        vessel_id = await pool.fetchval(
            """
            INSERT INTO vessels (user_id, name, vessel_type, flag_state, route_type, cargo_types)
            VALUES ($1, 'MV RegKnots Demo', 'cargo', 'US', 'coastal', ARRAY['dry_bulk'])
            RETURNING id
            """,
            user_id,
        )
        print(f"  Created vessel 'MV RegKnots Demo'  (id={vessel_id})")
    else:
        print("  Vessel already exists — skipped")

    await pool.close()
    print("\nSeed complete.")
    print(f"  Login: {SEED_EMAIL} / {SEED_PASSWORD}")


if __name__ == "__main__":
    asyncio.run(seed())

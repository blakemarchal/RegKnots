from fastapi import APIRouter
import redis.asyncio as aioredis

from app.config import settings
from app.db import get_pool

router = APIRouter(tags=["health"])

_SCHEMA_TABLES = [
    "users",
    "refresh_tokens",
    "vessels",
    "regulations",
    "conversations",
    "messages",
    "regulation_versions",
]


@router.get("/health")
async def health_check():
    checks = {"postgres": False, "redis": False}

    try:
        pool = await get_pool()
        row = await pool.fetchval("SELECT 1")
        checks["postgres"] = row == 1
    except Exception:
        pass

    try:
        r = aioredis.from_url(settings.redis_url)
        checks["redis"] = await r.ping()
        await r.aclose()
    except Exception:
        pass

    all_healthy = all(checks.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "checks": checks,
    }


@router.get("/health/db")
async def db_health():
    pool = await get_pool()

    # Check each table exists and get its row count
    table_counts: dict[str, int | str] = {}
    for table in _SCHEMA_TABLES:
        try:
            count = await pool.fetchval(f"SELECT COUNT(*) FROM {table}")
            table_counts[table] = count
        except Exception as exc:
            table_counts[table] = f"error: {exc}"

    all_ok = all(isinstance(v, int) for v in table_counts.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "table_counts": table_counts,
    }

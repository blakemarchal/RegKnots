import asyncpg
import redis.asyncio as aioredis
from app.config import settings
pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None
async def init_pool() -> asyncpg.Pool:
    global pool
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return pool
async def close_pool() -> None:
    global pool
    if pool:
        await pool.close()
        pool = None
async def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool not initialized")
    return pool

async def get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis

async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        _redis = None

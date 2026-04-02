import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from anthropic import AsyncAnthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_pool, close_pool
from app.routers import auth, health, chat, vessels, regulations, conversations

logger = logging.getLogger(__name__)

_API_DIR = Path(__file__).resolve().parent.parent  # apps/api/


async def _run_migrations() -> None:
    """Run alembic upgrade head. Only called in dev; harmless in prod too."""
    def _sync():
        from alembic.config import Config
        from alembic import command

        cfg = Config(str(_API_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(_API_DIR / "alembic"))
        command.upgrade(cfg, "head")

    await asyncio.to_thread(_sync)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.is_dev:
        logger.info("Running database migrations...")
        await _run_migrations()
        logger.info("Migrations complete.")
    await init_pool()
    app.state.anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
    app.state.openai_api_key = settings.openai_api_key
    yield
    await app.state.anthropic.close()
    await close_pool()


app = FastAPI(title="RegKnots API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(vessels.router)
app.include_router(regulations.router)
app.include_router(conversations.router)

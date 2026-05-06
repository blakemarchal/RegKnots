import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

import sentry_sdk
from anthropic import AsyncAnthropic
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        environment=settings.environment,
    )
from app.db import init_pool, close_pool, close_redis
from app.routers import admin, auth, billing, checklists, coming_up, contact, credentials, documents, dossier, export, health, chat, logs, me, onboarding, preferences, sea_service, sea_time, transcribe, vessels, regulations, conversations, notifications, support, survey, waitlist, web_fallback, workspaces

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
    await close_redis()
    await close_pool()


app = FastAPI(title="RegKnot API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"^https://([a-z0-9-]+\.)?regknots\.com$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(vessels.router)
app.include_router(documents.router)
app.include_router(documents.preview_router)
app.include_router(regulations.router)
app.include_router(conversations.router)
app.include_router(billing.router)
app.include_router(notifications.router)
app.include_router(waitlist.router)
app.include_router(contact.router)
app.include_router(support.router)
app.include_router(survey.router)
app.include_router(preferences.router)
app.include_router(credentials.router)
app.include_router(logs.router)
app.include_router(transcribe.router)
app.include_router(checklists.router)
app.include_router(export.router)
app.include_router(dossier.router)
app.include_router(coming_up.router)
app.include_router(sea_service.router)
app.include_router(sea_time.router)
app.include_router(me.router)
app.include_router(onboarding.router)
app.include_router(admin.router)
app.include_router(web_fallback.router)
app.include_router(workspaces.router)
app.include_router(workspaces.me_router)

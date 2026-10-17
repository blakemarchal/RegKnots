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
from app.hosts import cors_origins

def _scrub_sentry_event(event, hint):
    """2026-10-16 security review: no request bodies (questions, documents),
    query strings (verification / reset tokens), cookies, auth headers or
    user emails in Sentry. The SDK's own scrubber still runs on what's left."""
    request = event.get("request") or {}
    for key in ("data", "cookies", "query_string"):
        request.pop(key, None)
    if request.get("url"):
        request["url"] = request["url"].split("?")[0]
    headers = request.get("headers") or {}
    for key in list(headers):
        if key.lower() in ("cookie", "authorization", "x-forwarded-for", "referer"):
            headers.pop(key, None)
    user = event.get("user")
    if user:
        event["user"] = {"id": user["id"]} if user.get("id") else {}
    return event


if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        traces_sample_rate=0.1,
        environment=settings.environment,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_scrub_sentry_event,
    )
from app.db import init_pool, close_pool, close_redis
from app.routers import admin, admin_dashboard, admin_documents, admin_gaps, admin_pilots, auth, billing, checklists, coming_up, company_documents, contact, credentials, documents, dossier, export, health, chat, logs, me, onboarding, guest_chat, practice, preferences, public_regs, runner, sales, sea_service, sea_time, study, transcribe, user_documents, vessels, regulations, conversations, notifications, support, support_reports, survey, waitlist, web_fallback, whale_zones, workspaces

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
    # 2026-10-16 security review: never serve with development secrets.
    from app.config import production_problems
    problems = production_problems(settings)
    if problems:
        raise RuntimeError("Refusing to start: " + "; ".join(problems))
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
    # 2026-10-03 — our hosts only (app/hosts.py). The regex trusted every
    # https://*.regknots.com origin with credentials, the same names the
    # wildcard TLS gate handed certificates to.
    allow_origins=cors_origins(),
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
app.include_router(support_reports.router)   # 2026-10-16 — Report a problem
app.include_router(runner.router)            # 2026-10-16 — the laptop runner's job queue (token-gated)
app.include_router(sales.router)             # 2026-10-16 — admin-lite for a salesperson
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
app.include_router(admin_dashboard.router)   # 2026-09-29 — trends, funnel, revenue for /admin
app.include_router(web_fallback.router)
app.include_router(workspaces.router)
app.include_router(workspaces.me_router)
app.include_router(company_documents.router)   # 2026-09-27 — company documents in fleet chat
# Sprint D6.83 — Study Tools (quiz / guide generators + take-the-quiz sessions)
app.include_router(study.router)
# Sprint D6.97 #49 (2026-05-25) — public whale-zone map endpoint.
app.include_router(whale_zones.router)
app.include_router(practice.router)   # 2026-10-02 — free public USCG exam practice
app.include_router(public_regs.router)   # 2026-10-14 — public regulation pages (/regs)
app.include_router(guest_chat.router)    # 2026-10-14 — one free answer before signup
app.include_router(user_documents.router)   # 2026-10-05 — PDF / Word attachments in chat
app.include_router(admin_documents.router)  # 2026-10-05 — admin view of chat attachments
app.include_router(admin_gaps.router)       # 2026-10-08 — corpus gaps (answer pipeline phase 2)
app.include_router(admin_pilots.router)     # 2026-10-14 — Wheelhouse pilot codes and trials

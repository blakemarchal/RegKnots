from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolves to the monorepo root regardless of working directory
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    database_url: str = "postgresql://regknots:regknots_dev@localhost:5432/regknots"
    redis_url: str = "redis://localhost:6379/0"
    cors_origins: list[str] = ["http://localhost:3000"]
    environment: str = "development"

    # JWT
    jwt_secret_key: str = "dev-secret-key-change-in-production-use-REGKNOTS_JWT_SECRET_KEY"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # AI API keys — no REGKNOTS_ prefix in .env
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    # Email — no REGKNOTS_ prefix in .env
    resend_api_key: str = Field(default="", validation_alias="RESEND_API_KEY")

    # Legacy pre-launch pilot gate. Keep False post-launch — the standard
    # subscription gate in chat.py now handles trial expiry and limits.
    pilot_mode: bool = False

    # Stripe — no REGKNOTS_ prefix in .env
    stripe_secret_key: str = Field(default="", validation_alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", validation_alias="STRIPE_WEBHOOK_SECRET")
    # Legacy pre-D6.1 single-tier price IDs. Retained for backward compat
    # with any stale webhook traffic; new checkout flows do not use them.
    # Safe to unset once D6.1 two-tier pricing is verified live.
    stripe_price_id: str = Field(default="", validation_alias="STRIPE_PRICE_ID")
    stripe_annual_price_id: str = Field(default="", validation_alias="STRIPE_ANNUAL_PRICE_ID")
    # Sprint D6.1 two-tier pricing — six Stripe price IDs across Mate and
    # Captain products. See apps/api/app/plans.py for how these map to
    # subscription_tier + billing_interval + promo flag.
    stripe_price_mate_monthly: str = Field(
        default="", validation_alias="STRIPE_PRICE_MATE_MONTHLY"
    )
    stripe_price_mate_annual: str = Field(
        default="", validation_alias="STRIPE_PRICE_MATE_ANNUAL"
    )
    stripe_price_mate_promo: str = Field(
        default="", validation_alias="STRIPE_PRICE_MATE_PROMO"
    )
    stripe_price_captain_monthly: str = Field(
        default="", validation_alias="STRIPE_PRICE_CAPTAIN_MONTHLY"
    )
    stripe_price_captain_annual: str = Field(
        default="", validation_alias="STRIPE_PRICE_CAPTAIN_ANNUAL"
    )
    stripe_price_captain_promo: str = Field(
        default="", validation_alias="STRIPE_PRICE_CAPTAIN_PROMO"
    )
    app_url: str = "https://regknots.com"

    # File uploads
    upload_dir: str = str(_REPO_ROOT / "data" / "uploads" / "documents")

    # Sprint D6.7 — Caddy access-log analytics. Path to the directory
    # holding `regknots-access.log` and its rotated siblings. Set to ""
    # in dev (no Caddy running locally) — the /admin/traffic endpoint
    # returns an empty summary in that case instead of erroring.
    caddy_access_log_dir: str = Field(default="/var/log/caddy", validation_alias="CADDY_ACCESS_LOG_DIR")

    # ── Crew tier (D6.49) ────────────────────────────────────────────────
    # Master enable for the crew-tier feature. When false, the workspace
    # endpoints + UI are hidden from non-internal users; the migration
    # data model is harmless.
    crew_tier_enabled: bool = Field(
        default=False, validation_alias="CREW_TIER_ENABLED",
    )
    # Internal-only mode — when true (and crew_tier_enabled), only users
    # with is_internal=true can create or join workspaces. Used during
    # staged rollout for self-review before lifting to all users.
    crew_tier_internal_only: bool = Field(
        default=True, validation_alias="CREW_TIER_INTERNAL_ONLY",
    )

    # ── Web search fallback (D6.48 Phase 2) ──────────────────────────────
    # Master kill switch — flip to false on prod to disable fallback firing
    # for all users instantly without redeploying.
    web_fallback_enabled: bool = Field(
        default=True, validation_alias="WEB_FALLBACK_ENABLED",
    )
    # Cosine threshold below which we treat retrieval as a true corpus
    # gap and consider firing fallback. 0.5 is the v1 default — tune up
    # if fallback fires too often, down if it misses real gaps.
    web_fallback_cosine_threshold: float = Field(
        default=0.5, validation_alias="WEB_FALLBACK_COSINE_THRESHOLD",
    )
    # Per-user daily cap. Raises a soft block — user gets the original
    # hedge instead of a fallback after exceeding their daily quota.
    web_fallback_daily_cap: int = Field(
        default=10, validation_alias="WEB_FALLBACK_DAILY_CAP",
    )

    # Monitoring
    sentry_dsn: str = Field(default="", validation_alias="SENTRY_DSN")
    sentry_auth_token: str = Field(default="", validation_alias="SENTRY_AUTH_TOKEN")
    sentry_org: str = Field(default="", validation_alias="SENTRY_ORG")
    # Optional override for the /admin/sentry-issues project scope.
    # If unset, the endpoint queries the default list hardcoded in admin.py
    # (regknots-api + regknots-web). If set to a single slug, only that
    # project is queried. Comma-separated values are also accepted.
    sentry_project: str = Field(default="", validation_alias="SENTRY_PROJECT")

    @property
    def is_dev(self) -> bool:
        return self.environment == "development"

    model_config = SettingsConfigDict(
        env_prefix="REGKNOTS_",
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )


settings = Settings()

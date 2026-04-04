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

    # Pilot mode — extended trial for founding members
    pilot_mode: bool = True

    # Stripe — no REGKNOTS_ prefix in .env
    stripe_secret_key: str = Field(default="", validation_alias="STRIPE_SECRET_KEY")
    stripe_webhook_secret: str = Field(default="", validation_alias="STRIPE_WEBHOOK_SECRET")
    stripe_price_id: str = Field(default="", validation_alias="STRIPE_PRICE_ID")
    stripe_annual_price_id: str = Field(default="", validation_alias="STRIPE_ANNUAL_PRICE_ID")
    app_url: str = "https://regknots.com"

    # Monitoring
    sentry_dsn: str = Field(default="", validation_alias="SENTRY_DSN")

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

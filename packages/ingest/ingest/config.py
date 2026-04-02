from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolves to the monorepo root regardless of working directory
_REPO_ROOT = Path(__file__).resolve().parents[3]


class IngestSettings(BaseSettings):
    # Reads REGKNOTS_DATABASE_URL — same key as the API, no duplication in .env
    database_url: str = Field(
        default="postgresql://regknots:regknots_dev@localhost:5432/regknots",
        validation_alias="REGKNOTS_DATABASE_URL",
    )
    # Standard unprefixed names — what OpenAI/Anthropic SDKs expect
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str = Field(default="", validation_alias="ANTHROPIC_API_KEY")

    model_config = SettingsConfigDict(
        env_file=str(_REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )


settings = IngestSettings()

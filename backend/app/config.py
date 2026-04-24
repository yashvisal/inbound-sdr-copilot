from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "Inbound SDR Copilot API"
    environment: str = Field(default="development", alias="ENVIRONMENT")
    frontend_origin: str = Field(
        default="http://localhost:3000",
        alias="FRONTEND_ORIGIN",
    )
    news_api_key: str | None = Field(default=None, alias="NEWS_API_KEY")
    census_api_key: str | None = Field(default=None, alias="CENSUS_API_KEY")
    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")


@lru_cache
def get_settings() -> Settings:
    return Settings()

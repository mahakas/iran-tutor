"""Application settings, loaded only from environment / `backend/.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Typed settings. Provider URL, key and model names have no defaults on purpose."""

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    llm_base_url: str = Field(min_length=1)
    llm_api_key: str = Field(min_length=1)

    # Compare-mode only (test_ingest.py): A/B
    vision_model_a: str = Field(min_length=1)
    vision_model_b: str = Field(min_length=1)

    # Production ingestion: primary + optional escalation
    vision_model_primary: str = Field(min_length=1)
    vision_model_escalation: str | None = None
    escalate_figures: bool = False

    llm_timeout: float = Field(default=120, gt=0)
    max_concurrency: int = Field(default=3, ge=1)

    database_url: str = Field(min_length=1)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()  # type: ignore[call-arg]

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

    demo_mode: bool = False
    llm_base_url: str = Field(min_length=1)
    llm_api_key: str = Field(min_length=1)

    # Compare-mode only (test_ingest.py): A/B
    vision_model_a: str = Field(min_length=1)
    vision_model_b: str = Field(min_length=1)

    # Production ingestion: primary + optional escalation
    vision_model_primary: str = Field(min_length=1)
    vision_model_escalation: str | None = None
    tutor_model: str | None = None
    speech_to_text_model: str | None = None
    audio_base_url: str | None = None
    audio_api_key: str | None = None
    escalate_figures: bool = False

    llm_timeout: float = Field(default=120, gt=0)
    max_concurrency: int = Field(default=3, ge=1)

    database_url: str = Field(min_length=1)

    # Phase 2: textbook vector search. The embedding provider can differ from
    # the chat/vision provider; empty values fall back to the LLM credentials.
    qdrant_url: str = "http://127.0.0.1:6333"
    qdrant_collection: str = "iran_textbooks"
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    embedding_model: str = "text-embedding-3-small"
    embedding_dimension: int = Field(default=1536, gt=0)


@lru_cache
def get_settings() -> Settings:
    """Return the cached settings instance."""
    return Settings()  # type: ignore[call-arg]

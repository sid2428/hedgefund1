"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly-typed application settings.

    Values are loaded from (in order):
      1. Environment variables (highest priority).
      2. A `.env` file in the project root.
      3. The defaults defined here.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Database ---
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://mosaic:devpassword@localhost:5432/mosaic",
        description="Async SQLAlchemy URL. Must use the asyncpg driver for production.",
    )
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT: int = 30
    DB_ECHO: bool = False

    # --- Redis / Celery ---
    REDIS_URL: str = Field(default="redis://localhost:6379/0")

    # --- AI providers ---
    # Primary LLM is Groq (free tier, OpenAI-compatible chat completions API).
    GROQ_API_KEY: str = Field(default="", description="Groq API key.")
    GROQ_MODEL: str = Field(
        default="llama-3.3-70b-versatile",
        description="Groq model. llama-3.3-70b-versatile has 128k context.",
    )
    GROQ_MAX_TOKENS: int = 4096
    GROQ_TIMEOUT_SECONDS: float = 120.0

    OPENAI_API_KEY: str = Field(default="", description="OpenAI API key (embeddings only).")
    OPENAI_EMBEDDING_MODEL: str = Field(default="text-embedding-3-large")
    OPENAI_EMBEDDING_DIM: int = 3072

    # --- SEC EDGAR ---
    EDGAR_USER_AGENT: str = Field(
        default="Mosaic Research research@example.com",
        description="EDGAR ToS requires a real contact User-Agent.",
    )
    EDGAR_BASE_URL: str = "https://data.sec.gov"
    EDGAR_SEARCH_URL: str = "https://efts.sec.gov/LATEST/search-index"
    # SEC enforces 10 req/sec per IP across all EDGAR domains; breaching it
    # returns 403 and blocks the IP for roughly 10 minutes. We run at 8 to keep
    # headroom for retries and any concurrent process sharing the address.
    EDGAR_RATE_LIMIT_RPS: float = 8.0

    # --- Pipeline tuning ---
    EXTRACTOR_MAX_TOKENS_PER_CHUNK: int = 6000
    DELTA_SIGNIFICANCE_THRESHOLD: float = 0.6
    THESIS_MIN_CONFIDENCE: float = 0.5
    GRAPH_FUZZY_MATCH_THRESHOLD: int = 85  # rapidfuzz score 0-100

    # --- App ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    ENVIRONMENT: Literal["development", "staging", "production"] = "development"
    ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    @field_validator("DATABASE_URL")
    @classmethod
    def _validate_db_url(cls, v: str) -> str:
        if not v.startswith(("postgresql+asyncpg://", "sqlite+aiosqlite://")):
            raise ValueError(
                "DATABASE_URL must use postgresql+asyncpg or sqlite+aiosqlite driver."
            )
        return v

    @field_validator("EDGAR_USER_AGENT")
    @classmethod
    def _validate_edgar_ua(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError(
                "EDGAR_USER_AGENT must contain a contact email per SEC ToS."
            )
        return v

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite+aiosqlite://")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance. Cached so we read env once per process."""
    return Settings()


settings = get_settings()

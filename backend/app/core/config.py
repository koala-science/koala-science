from typing import Any, Optional

from pydantic import PostgresDsn, field_validator, ValidationInfo
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Koala Science"
    API_V1_STR: str = "/api/v1"

    POSTGRES_SERVER: str = "localhost"
    POSTGRES_USER: str = "worknomic"
    POSTGRES_PASSWORD: str = "worknomic_password"
    POSTGRES_DB: str = "coalescence"
    POSTGRES_PORT: int = 5432
    DATABASE_URL: Optional[PostgresDsn] = None

    REDIS_URL: str = "redis://localhost:6379/0"
    TEMPORAL_HOST: str = "localhost:7233"

    # Auth
    SECRET_KEY: str = "CHANGE-ME-in-production-use-openssl-rand-hex-32"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 10080  # 7 days
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"
    LEADERBOARD_PASSWORD: str = "Mont-Saint-Hilaire"

    # Gemini (for embeddings / semantic search, and comment moderation)
    GEMINI_API_KEY: str = ""
    GEMINI_MODERATION_MODEL: str = "gemini-2.5-flash"

    # Hugging Face (for gated dataset access during ingestion)
    HF_TOKEN: str = ""

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"

    # Storage
    STORAGE_BACKEND: str = "local"  # "local" or "gcs"
    STORAGE_DIR: str = "/storage"   # Local filesystem path (used when STORAGE_BACKEND=local)
    GCS_STORAGE_BUCKET: str = ""    # GCS bucket name (used when STORAGE_BACKEND=gcs)

    # ORCID OAuth (for identity verification, not login)
    ORCID_CLIENT_ID: str = ""
    ORCID_CLIENT_SECRET: str = ""
    ORCID_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/orcid/callback"

    # CORS — comma-separated origins, parsed into a list. Default mirrors the
    # previous hard-coded localhost set so dev parity is preserved.
    CORS_ORIGINS: list[str] = [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://frontend:3000",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors_origins(cls, v: Any) -> Any:
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def assemble_db_connection(cls, v: Optional[str], info: ValidationInfo) -> Any:
        if isinstance(v, str) and v:
            return v
        return PostgresDsn.build(
            scheme="postgresql+asyncpg",
            username=info.data.get("POSTGRES_USER"),
            password=info.data.get("POSTGRES_PASSWORD"),
            host=info.data.get("POSTGRES_SERVER"),
            port=info.data.get("POSTGRES_PORT"),
            path=info.data.get("POSTGRES_DB") or "",
        )

    model_config = SettingsConfigDict(case_sensitive=True, env_file=".env")


settings = Settings()

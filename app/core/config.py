"""
Application settings loaded from the ``.env`` file via Pydantic Settings.

A single ``settings`` singleton is instantiated at module import time and
shared across the entire application. Celery workers import it too, so every
value is available in both async FastAPI context and sync Celery context.
"""

from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All application configuration, loaded from environment variables or ``.env``."""

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------
    DATABASE_URL_ASYNC: str
    """asyncpg connection URL used by the FastAPI async engine (e.g. ``postgresql+asyncpg://...``)."""

    DATABASE_URL_SYNC: str
    """psycopg2 connection URL used by the Celery sync engine (e.g. ``postgresql://...``)."""

    # ------------------------------------------------------------------
    # Redis / Celery
    # ------------------------------------------------------------------
    REDIS_URL: str
    """Redis connection URL used as both Celery broker and result backend."""

    # ------------------------------------------------------------------
    # Security
    # ------------------------------------------------------------------
    SECRET_KEY: str
    """HS256 signing key for JWT tokens. Keep this secret and rotate periodically."""

    ALGORITHM: str
    """JWT signing algorithm. Defaults to ``HS256``."""

    ACCESS_TOKEN_EXPIRE_MINUTES: int
    """JWT lifetime in minutes."""

    # ------------------------------------------------------------------
    # Embedding model
    # ------------------------------------------------------------------
    EMBEDDING_MODEL: str
    """HuggingFace model name used for both ingestion and query embedding (e.g. ``all-MiniLM-L6-v2``)."""

    CHUNK_SIZE: int
    """Maximum character length of each text chunk fed to the embedding model."""

    CHUNK_OVERLAP: int
    """Number of characters to overlap between adjacent chunks to preserve context at boundaries."""

    # ------------------------------------------------------------------
    # Encoding
    # ------------------------------------------------------------------
    ENCODING: str
    """Text encoding used for password hashing and JWT operations (e.g. ``utf-8``)."""

    # ------------------------------------------------------------------
    # Document storage
    # ------------------------------------------------------------------
    DOCUMENT_STORAGE: Literal["LOCAL", "CLOUD_STORAGE"] = "LOCAL"
    """Storage backend: ``LOCAL`` writes to disk; ``CLOUD_STORAGE`` uses AWS S3."""

    LOCAL_UPLOAD_DIR: str = "uploads"
    """Root directory for local file storage. Only used when ``DOCUMENT_STORAGE=LOCAL``."""

    # ------------------------------------------------------------------
    # AWS S3 (required when DOCUMENT_STORAGE=CLOUD_STORAGE)
    # ------------------------------------------------------------------
    AWS_ACCESS_KEY_ID: str | None = None
    """AWS access key. Required when ``DOCUMENT_STORAGE=CLOUD_STORAGE``."""

    AWS_SECRET_ACCESS_KEY: str | None = None
    """AWS secret key. Required when ``DOCUMENT_STORAGE=CLOUD_STORAGE``."""

    AWS_REGION: str = "ap-south-1"
    """AWS region where the S3 bucket resides."""

    S3_BUCKET_NAME: str = "agentic-rag-api"
    """S3 bucket name. Documents are stored at ``BACKEND/{company_id}/{stem}_{timestamp}.pdf``."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @model_validator(mode="after")
    def _validate_cloud_storage(self) -> "Settings":
        """Fail fast at startup if S3 credentials are missing when cloud storage is enabled."""
        if self.DOCUMENT_STORAGE == "CLOUD_STORAGE":
            if not self.AWS_ACCESS_KEY_ID or not self.AWS_SECRET_ACCESS_KEY:
                raise ValueError(
                    "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required " "when DOCUMENT_STORAGE=CLOUD_STORAGE"
                )
        return self


settings = Settings()

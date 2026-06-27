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

    DB_POOL_SIZE: int = 10
    """Async SQLAlchemy pool size for API DB connections."""

    DB_MAX_OVERFLOW: int = 20
    """Additional overflow connections allowed beyond ``DB_POOL_SIZE``."""

    # ------------------------------------------------------------------
    # Redis / Celery
    # ------------------------------------------------------------------
    REDIS_URL: str
    """Redis connection URL used as both Celery broker and result backend."""

    LOGIN_RATE_LIMIT_ATTEMPTS: int = 10
    """Maximum login attempts per key (IP+username) within LOGIN_RATE_LIMIT_WINDOW_SECONDS."""

    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 60
    """Login rate limit window in seconds."""

    CHAT_RATE_LIMIT_REQUESTS: int = 30
    """Maximum chat invoke requests per user within CHAT_RATE_LIMIT_WINDOW_SECONDS."""

    CHAT_RATE_LIMIT_WINDOW_SECONDS: int = 60
    """Chat rate limit window in seconds."""

    CHAT_IDEMPOTENCY_TTL_SECONDS: int = 300
    """How long chat idempotency responses are cached in Redis."""

    TOKEN_SESSION_CACHE_TTL_SECONDS: int = 60
    """TTL for valid JWT session-cache entries to reduce repeated DB lookups."""

    VECTOR_SEARCH_CACHE_TTL_SECONDS: int = 300
    """TTL for vector-search context cache entries keyed by company and query."""

    CHAT_HISTORY_CACHE_TTL_SECONDS: int = 60
    """TTL for chat history read caches (conversation list/messages)."""

    DOCUMENT_METADATA_CACHE_TTL_SECONDS: int = 60
    """TTL for document list/get response caches."""

    DEFAULT_LIST_LIMIT: int = 50
    """Default page size for list endpoints."""

    MAX_LIST_LIMIT: int = 200
    """Hard upper bound for list endpoint page size."""

    MAX_UPLOAD_BYTES: int = 25 * 1024 * 1024
    """Maximum accepted upload size in bytes for document ingestion."""

    READINESS_REQUIRE_REDIS: bool = True
    """When true, /readyz requires Redis connectivity in addition to database readiness."""

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

"""Pytest fixtures and lightweight async test helpers."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

# Ensure settings can initialize in CI even when no .env is provided.
os.environ.setdefault("DATABASE_URL_ASYNC", "postgresql+asyncpg://test:test@localhost:5432/test")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("ALGORITHM", "HS256")
os.environ.setdefault("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
os.environ.setdefault("CHUNK_SIZE", "1000")
os.environ.setdefault("CHUNK_OVERLAP", "200")
os.environ.setdefault("ENCODING", "utf-8")

from app.agent.tools import vector_search
from app.main import app


@pytest.fixture
def test_client() -> TestClient:
    """FastAPI test client with clean dependency overrides per test."""
    app.dependency_overrides = {}
    original_warmup = vector_search.warmup_vector_search
    vector_search.warmup_vector_search = lambda: False
    client = TestClient(app)
    try:
        yield client
    finally:
        vector_search.warmup_vector_search = original_warmup
        app.dependency_overrides = {}


@pytest.fixture
def mock_db() -> AsyncMock:
    """Async SQLAlchemy session mock used by service and endpoint tests."""
    db = AsyncMock()
    db.execute = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    db.add = Mock()
    return db


@pytest.fixture
def override_db(mock_db: AsyncMock):
    """Dependency override for get_db returning the provided mock db."""

    async def _override() -> AsyncGenerator[AsyncMock]:
        yield mock_db

    return _override

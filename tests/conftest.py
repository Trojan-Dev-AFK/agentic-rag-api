"""Pytest fixtures and lightweight async test helpers."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

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

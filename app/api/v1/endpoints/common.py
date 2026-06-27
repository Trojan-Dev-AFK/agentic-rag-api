"""Shared endpoint-layer helpers for building service kwargs."""

from __future__ import annotations

from typing import Any

from app.db.models import User


def build_list_service_kwargs(
    *,
    db: Any,
    current_user: User,
    limit: int | None = None,
    offset: int | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build service kwargs while preserving optional-parameter compatibility for tests/mocks."""
    kwargs: dict[str, Any] = {
        "db": db,
        "current_user": current_user,
        **extra,
    }
    if limit is not None:
        kwargs["limit"] = limit
    if offset is not None:
        kwargs["offset"] = offset
    return kwargs

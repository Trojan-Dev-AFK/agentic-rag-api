"""Shared helpers for service-layer data access and pagination."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.db.models import Company

logger = get_logger(__name__)


def sanitize_pagination(*, limit: int | None, offset: int | None) -> tuple[int, int]:
    """Normalize list pagination parameters using configured defaults and limits."""
    safe_limit = settings.DEFAULT_LIST_LIMIT if limit is None else limit
    safe_limit = max(1, min(safe_limit, settings.MAX_LIST_LIMIT))
    safe_offset = 0 if offset is None else max(0, offset)
    return safe_limit, safe_offset


async def get_by_id_or_404(
    *,
    db: AsyncSession,
    model: type[Any],
    entity_id: str,
    detail: str,
    log_message: str,
    log_extra: dict[str, Any] | None = None,
) -> Any:
    """Fetch an entity by UUID and raise HTTP 404 when absent."""
    result = await db.execute(select(model).filter(model.id == entity_id))
    entity = result.scalar_one_or_none()
    if entity is None:
        logger.warning(log_message, extra=log_extra or {"entity_id": entity_id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return entity


async def get_company_or_400(*, db: AsyncSession, company_id: str, actor_id: str | None = None) -> Company:
    """Fetch a company by UUID and raise HTTP 400 when absent."""
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        logger.warning(
            "Company not found",
            extra={"company_id": company_id, "actor": actor_id},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")
    return company

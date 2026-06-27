"""Business logic for company-management operations."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.db.models import Company, User
from app.schemas.companies import CompanyCreate, CompanyUpdate

logger = get_logger(__name__)


def _sanitize_pagination(*, limit: int | None, offset: int | None) -> tuple[int, int]:
    safe_limit = settings.DEFAULT_LIST_LIMIT if limit is None else limit
    safe_limit = max(1, min(safe_limit, settings.MAX_LIST_LIMIT))
    safe_offset = 0 if offset is None else max(0, offset)
    return safe_limit, safe_offset


async def create_company(*, company_data: CompanyCreate, db: AsyncSession, current_user: User) -> Company:
    """Create a company, enforcing unique name constraint at application level."""
    result = await db.execute(select(Company).filter(Company.name == company_data.name))
    if result.scalar_one_or_none():
        logger.warning(
            "Company creation failed — name already exists",
            extra={"company_name": company_data.name, "actor": current_user.id},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company with this name already exists")

    company = Company(
        name=company_data.name,
        industry=company_data.industry,
        description=company_data.description,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)

    logger.info(
        "Company created",
        extra={"company_id": company.id, "company_name": company.name, "actor": current_user.id},
    )
    return company


async def list_companies(
    *,
    db: AsyncSession,
    current_user: User,
    limit: int | None = None,
    offset: int | None = None,
) -> list[Company]:
    """List all companies ordered alphabetically."""
    safe_limit, safe_offset = _sanitize_pagination(limit=limit, offset=offset)
    result = await db.execute(select(Company).order_by(Company.name).offset(safe_offset).limit(safe_limit))
    companies = result.scalars().all()
    logger.info("Companies listed", extra={"count": len(companies), "actor": current_user.id})
    return list(companies)


async def get_company(*, company_id: str, db: AsyncSession, current_user: User) -> Company:
    """Fetch a company by UUID or raise 404."""
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        logger.warning("Company not found", extra={"company_id": company_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    logger.info("Company fetched", extra={"company_id": company_id, "actor": current_user.id})
    return company


async def update_company(
    *, company_id: str, update_data: CompanyUpdate, db: AsyncSession, current_user: User
) -> Company:
    """Apply partial updates to company fields and persist changes."""
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        logger.warning("Company update failed — not found", extra={"company_id": company_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    changed = {}
    if update_data.name is not None:
        changed["name"] = update_data.name
        company.name = update_data.name
    if update_data.industry is not None:
        changed["industry"] = update_data.industry
        company.industry = update_data.industry
    if update_data.description is not None:
        changed["description"] = update_data.description
        company.description = update_data.description

    await db.commit()
    await db.refresh(company)

    logger.info(
        "Company updated",
        extra={"company_id": company_id, "changed_fields": list(changed.keys()), "actor": current_user.id},
    )
    return company


async def delete_company(*, company_id: str, db: AsyncSession, current_user: User) -> None:
    """Delete a company and rely on configured cascades for related entities."""
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        logger.warning("Company delete failed — not found", extra={"company_id": company_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    await db.delete(company)
    await db.commit()

    logger.warning(
        "Company deleted (cascades users, documents, chunks)",
        extra={"company_id": company_id, "company_name": company.name, "actor": current_user.id},
    )

"""Company management endpoints — Super Admin only."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_super_admin
from app.core.logger import get_logger
from app.db.models import Company
from app.db.session import get_db
from app.schemas.companies import CompanyCreate, CompanyResponse, CompanyUpdate

logger = get_logger(__name__)
router = APIRouter()


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    company_data: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """Create a new company tenant (super admin only)."""
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


@router.get("/", response_model=list[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """Return all companies ordered by name (super admin only)."""
    result = await db.execute(select(Company).order_by(Company.name))
    companies = result.scalars().all()
    logger.info("Companies listed", extra={"count": len(companies), "actor": current_user.id})
    return companies


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """Fetch a single company by ID (super admin only)."""
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        logger.warning("Company not found", extra={"company_id": company_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    logger.info("Company fetched", extra={"company_id": company_id, "actor": current_user.id})
    return company


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    update_data: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """Update company fields. Only provided fields are changed (super admin only)."""
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


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_super_admin),
):
    """Delete a company and cascade-delete all its users, documents, and chunks (super admin only)."""
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
    return None

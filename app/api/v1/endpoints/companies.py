"""Company management endpoints — Super Admin only."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_super_admin
from app.db.models import User
from app.db.session import get_db
from app.schemas.companies import CompanyCreate, CompanyResponse, CompanyUpdate
from app.services import companies_service

router = APIRouter()


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(
    company_data: CompanyCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Create a new company tenant (super admin only)."""
    return await companies_service.create_company(
        company_data=company_data,
        db=db,
        current_user=current_user,
    )


@router.get("/", response_model=list[CompanyResponse])
async def list_companies(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Return all companies ordered by name (super admin only)."""
    return await companies_service.list_companies(db=db, current_user=current_user)


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Fetch a single company by ID (super admin only)."""
    return await companies_service.get_company(company_id=company_id, db=db, current_user=current_user)


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: str,
    update_data: CompanyUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Update company fields. Only provided fields are changed (super admin only)."""
    return await companies_service.update_company(
        company_id=company_id,
        update_data=update_data,
        db=db,
        current_user=current_user,
    )


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_super_admin),
):
    """Delete a company and cascade-delete all its users, documents, and chunks (super admin only)."""
    await companies_service.delete_company(company_id=company_id, db=db, current_user=current_user)
    return None

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_super_admin
from app.db.models import Company
from app.db.session import get_db
from app.schemas.companies import CompanyCreate, CompanyUpdate, CompanyResponse

router = APIRouter()


@router.post("/", response_model=CompanyResponse, status_code=status.HTTP_201_CREATED)
async def create_company(company_data: CompanyCreate, db: AsyncSession = Depends(get_db), current_user=Depends(require_super_admin)):
    result = await db.execute(select(Company).filter(Company.name == company_data.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company with this name already exists")

    company = Company(
        name=company_data.name,
        industry=company_data.industry,
        description=company_data.description,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


@router.get("/", response_model=List[CompanyResponse])
async def list_companies(db: AsyncSession = Depends(get_db), current_user=Depends(require_super_admin)):
    result = await db.execute(select(Company).order_by(Company.name))
    companies = result.scalars().all()
    return companies


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(require_super_admin)):
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return company


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(company_id: str, update_data: CompanyUpdate, db: AsyncSession = Depends(get_db), current_user=Depends(require_super_admin)):
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    if update_data.name is not None:
        company.name = update_data.name
    if update_data.industry is not None:
        company.industry = update_data.industry
    if update_data.description is not None:
        company.description = update_data.description

    await db.commit()
    await db.refresh(company)
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(company_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(require_super_admin)):
    result = await db.execute(select(Company).filter(Company.id == company_id))
    company = result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")

    await db.delete(company)
    await db.commit()
    return None

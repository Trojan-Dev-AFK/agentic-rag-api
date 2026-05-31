from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.security import get_password_hash
from app.db.models import User, UserRole, Company
from app.db.session import get_db
from app.schemas.users import UserCreate, UserUpdate, UserResponse

router = APIRouter()


def _assert_same_company(current_user: User, target_company_id: Optional[str]):
    """Verify admin can only manage users in their own company."""
    if target_company_id != current_user.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins may only manage users within their own company.",
        )


# ============================================================================
# USER MANAGEMENT ENDPOINTS (CRUD - Admin Only)
# ============================================================================

@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_data: UserCreate, db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """Create a new user (admin only). Only admins can create users in the system."""
    result = await db.execute(select(User).filter(User.username == user_data.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    _assert_same_company(current_user, user_data.company_id)

    company_result = await db.execute(select(Company).filter(Company.id == user_data.company_id))
    company = company_result.scalar_one_or_none()
    if not company:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")

    hashed_pw = get_password_hash(user_data.password)
    new_user = User(
        username=user_data.username,
        hashed_password=hashed_pw,
        role=user_data.role,
        company_id=user_data.company_id,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        role=new_user.role,
        company_id=new_user.company_id,
        company_name=company.name,
        created_at=new_user.created_at,
    )


@router.get("/", response_model=List[UserResponse])
async def list_users(db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """List users (admin only, scoped to admin's company if not global admin)."""
    query = select(User).filter(User.company_id == current_user.company_id).order_by(User.username)

    result = await db.execute(query)
    users = result.scalars().all()
    return [
        UserResponse(
            id=user.id,
            username=user.username,
            role=user.role,
            company_id=user.company_id,
            company_name=user.company.name if user.company else None,
            created_at=user.created_at,
        )
        for user in users
    ]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(user_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """Get a specific user (admin only)."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_same_company(current_user, user.company_id)

    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=user.company.name if user.company else None,
        created_at=user.created_at,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, update_data: UserUpdate, db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """Update a user (admin only)."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_same_company(current_user, user.company_id)
    if update_data.company_id is not None:
        _assert_same_company(current_user, update_data.company_id)

    if update_data.password:
        user.hashed_password = get_password_hash(update_data.password)
    if update_data.role is not None:
        user.role = update_data.role
    if update_data.company_id is not None:
        company_result = await db.execute(select(Company).filter(Company.id == update_data.company_id))
        company = company_result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")
        user.company_id = update_data.company_id

    await db.commit()
    await db.refresh(user)
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=user.company.name if user.company else None,
        created_at=user.created_at,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db), current_user=Depends(require_admin)):
    """Delete a user (admin only)."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_same_company(current_user, user.company_id)

    await db.delete(user)
    await db.commit()
    return None

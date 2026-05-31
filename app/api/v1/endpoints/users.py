from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin
from app.core.logger import get_logger
from app.core.security import get_password_hash
from app.db.models import Company, User
from app.db.session import get_db
from app.schemas.users import UserCreate, UserResponse, UserUpdate

logger = get_logger(__name__)
router = APIRouter()


def _assert_same_company(current_user: User, target_company_id: str | None) -> None:
    """Raise 403 if the target company doesn't match the admin's company."""
    if target_company_id != current_user.company_id:
        logger.warning(
            "Cross-company access denied",
            extra={
                "actor": current_user.id,
                "actor_company": current_user.company_id,
                "target_company": target_company_id,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins may only manage users within their own company.",
        )


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Create a new user in the admin's company."""
    result = await db.execute(select(User).filter(User.username == user_data.username))
    if result.scalar_one_or_none():
        logger.warning(
            "User creation failed — username taken",
            extra={"username": user_data.username, "actor": current_user.id},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

    _assert_same_company(current_user, user_data.company_id)

    company_result = await db.execute(select(Company).filter(Company.id == user_data.company_id))
    company = company_result.scalar_one_or_none()
    if not company:
        logger.warning(
            "User creation failed — company not found",
            extra={"company_id": user_data.company_id, "actor": current_user.id},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")

    new_user = User(
        username=user_data.username,
        hashed_password=get_password_hash(user_data.password),
        role=user_data.role,
        company_id=user_data.company_id,
    )
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)

    logger.info(
        "User created",
        extra={
            "user_id": new_user.id,
            "username": new_user.username,
            "role": str(new_user.role),
            "company_id": new_user.company_id,
            "actor": current_user.id,
        },
    )
    return UserResponse(
        id=new_user.id,
        username=new_user.username,
        role=new_user.role,
        company_id=new_user.company_id,
        company_name=company.name,
        created_at=new_user.created_at,
    )


@router.get("/", response_model=list[UserResponse])
async def list_users(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """List all users in the admin's company."""
    result = await db.execute(select(User).filter(User.company_id == current_user.company_id).order_by(User.username))
    users = result.scalars().all()
    logger.info(
        "Users listed",
        extra={"company_id": current_user.company_id, "count": len(users), "actor": current_user.id},
    )
    return [
        UserResponse(
            id=u.id,
            username=u.username,
            role=u.role,
            company_id=u.company_id,
            company_name=u.company.name if u.company else None,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Fetch a specific user (must belong to admin's company)."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User not found", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_same_company(current_user, user.company_id)

    logger.info("User fetched", extra={"user_id": user_id, "actor": current_user.id})
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=user.company.name if user.company else None,
        created_at=user.created_at,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    update_data: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Update a user (must belong to admin's company)."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User update failed — not found", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_same_company(current_user, user.company_id)

    changed = []
    if update_data.password:
        user.hashed_password = get_password_hash(update_data.password)
        changed.append("password")
    if update_data.role is not None:
        if update_data.company_id is not None:
            _assert_same_company(current_user, update_data.company_id)
        user.role = update_data.role
        changed.append("role")
    if update_data.company_id is not None:
        company_result = await db.execute(select(Company).filter(Company.id == update_data.company_id))
        company = company_result.scalar_one_or_none()
        if not company:
            logger.warning(
                "User update failed — target company not found",
                extra={"company_id": update_data.company_id, "actor": current_user.id},
            )
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")
        user.company_id = update_data.company_id
        changed.append("company_id")

    await db.commit()
    await db.refresh(user)

    logger.info(
        "User updated",
        extra={"user_id": user_id, "changed_fields": changed, "actor": current_user.id},
    )
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=user.company.name if user.company else None,
        created_at=user.created_at,
    )


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_admin),
):
    """Delete a user and all their token sessions."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User delete failed — not found", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    _assert_same_company(current_user, user.company_id)

    await db.delete(user)
    await db.commit()

    logger.warning(
        "User deleted",
        extra={"user_id": user_id, "username": user.username, "actor": current_user.id},
    )
    return None

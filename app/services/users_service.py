"""Business logic for user-management operations."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logger import get_logger
from app.core.security import get_password_hash
from app.db.models import Company, User, UserRole
from app.schemas.users import UserCreate, UserResponse, UserUpdate

logger = get_logger(__name__)

_SUPER_ADMIN_ROLE_ERROR = "The super_admin role cannot be assigned via this endpoint. Use the bootstrap script."


def _assert_same_company(current_user: User, target_company_id: str | None) -> None:
    """Raise 403 when company-scoped admin attempts cross-company user operation."""
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


def _to_user_response(user: User) -> UserResponse:
    """Map ORM user entity to API response payload."""
    return UserResponse(
        id=user.id,
        username=user.username,
        role=user.role,
        company_id=user.company_id,
        company_name=user.company.name if user.company else None,
        created_at=user.created_at,
    )


async def create_user(*, user_data: UserCreate, db: AsyncSession, current_user: User) -> UserResponse:
    """Create a company-scoped user with RBAC and uniqueness checks."""
    if user_data.role == UserRole.SUPER_ADMIN:
        logger.warning(
            "Attempt to create super_admin via users endpoint",
            extra={"actor": current_user.id},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_SUPER_ADMIN_ROLE_ERROR)

    if current_user.role == UserRole.ADMIN:
        _assert_same_company(current_user, user_data.company_id)

    result = await db.execute(select(User).filter(User.username == user_data.username))
    if result.scalar_one_or_none():
        logger.warning(
            "User creation failed — username taken",
            extra={"username": user_data.username, "actor": current_user.id},
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already registered")

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
            "actor_role": str(current_user.role),
        },
    )
    return _to_user_response(new_user)


async def list_users(*, company_id: str | None, db: AsyncSession, current_user: User) -> list[UserResponse]:
    """List users based on actor role and optional company filter."""
    if current_user.role == UserRole.ADMIN:
        query = select(User).filter(User.company_id == current_user.company_id).order_by(User.username)
    elif company_id:
        query = select(User).filter(User.company_id == company_id).order_by(User.username)
    else:
        query = select(User).filter(User.role != UserRole.SUPER_ADMIN).order_by(User.username)

    result = await db.execute(query)
    users = result.scalars().all()

    logger.info(
        "Users listed",
        extra={
            "count": len(users),
            "actor": current_user.id,
            "actor_role": str(current_user.role),
            "filter_company": company_id or (current_user.company_id if current_user.role == UserRole.ADMIN else "all"),
        },
    )
    return [_to_user_response(user) for user in users]


async def get_user(*, user_id: str, db: AsyncSession, current_user: User) -> UserResponse:
    """Fetch a user by UUID with role-aware company scope checks."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User not found", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if current_user.role == UserRole.ADMIN:
        _assert_same_company(current_user, user.company_id)

    logger.info(
        "User fetched",
        extra={"user_id": user_id, "actor": current_user.id, "actor_role": str(current_user.role)},
    )
    return _to_user_response(user)


async def update_user(*, user_id: str, update_data: UserUpdate, db: AsyncSession, current_user: User) -> UserResponse:
    """Update mutable fields on a user while enforcing RBAC and integrity checks."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User update failed — not found", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if current_user.role == UserRole.ADMIN:
        _assert_same_company(current_user, user.company_id)
        if update_data.company_id is not None:
            _assert_same_company(current_user, update_data.company_id)

    if update_data.role == UserRole.SUPER_ADMIN:
        logger.warning(
            "Attempt to promote user to super_admin",
            extra={"target_user": user_id, "actor": current_user.id},
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_SUPER_ADMIN_ROLE_ERROR)

    changed = []
    if update_data.password:
        user.hashed_password = get_password_hash(update_data.password)
        changed.append("password")
    if update_data.role is not None:
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
        extra={
            "user_id": user_id,
            "changed_fields": changed,
            "actor": current_user.id,
            "actor_role": str(current_user.role),
        },
    )
    return _to_user_response(user)


async def delete_user(*, user_id: str, db: AsyncSession, current_user: User) -> None:
    """Delete a user and cascaded token sessions with scope and self-delete protections."""
    result = await db.execute(select(User).filter(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("User delete failed — not found", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.id == current_user.id:
        logger.warning("Self-deletion attempt blocked", extra={"user_id": user_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot delete your own account.")

    if current_user.role == UserRole.ADMIN:
        _assert_same_company(current_user, user.company_id)

    await db.delete(user)
    await db.commit()

    logger.warning(
        "User deleted",
        extra={
            "user_id": user_id,
            "username": user.username,
            "actor": current_user.id,
            "actor_role": str(current_user.role),
        },
    )

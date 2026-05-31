"""
User management endpoints.

Access rules:

- ``super_admin``  — full access across all companies; cannot assign ``super_admin`` role.
- ``admin``        — scoped to their own company only; cannot assign ``super_admin`` role.
- ``employee``     — no access (403 on all endpoints).

Workflow for onboarding a new company:
1. ``super_admin`` creates the company via ``POST /v1/companies/``.
2. ``super_admin`` creates the first ``admin`` user via ``POST /v1/users/``.
3. That company admin manages subsequent users within their own company.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_or_super_admin
from app.core.logger import get_logger
from app.core.security import get_password_hash
from app.db.models import Company, User, UserRole
from app.db.session import get_db
from app.schemas.users import UserCreate, UserResponse, UserUpdate

logger = get_logger(__name__)
router = APIRouter()

_SUPER_ADMIN_ROLE_ERROR = "The super_admin role cannot be assigned via this endpoint. Use the bootstrap script."


def _assert_same_company(current_user: User, target_company_id: Optional[str]) -> None:
    """
    Raise 403 if a company admin tries to act on a user outside their company.

    Not called for ``super_admin`` — they have cross-company access.
    """
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


@router.post(
    "/",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    responses={
        400: {"description": "Username taken or company not found."},
        403: {"description": "Insufficient role, cross-company attempt, or super_admin role assignment."},
    },
)
async def create_user(
    user_data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Create a new user (``admin`` or ``employee``) inside a company.

    **super_admin** can create users in any company.
    **admin** can only create users in their own company.
    Neither role may assign ``super_admin`` — use the bootstrap script for that.
    """
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
    company_id: Optional[str] = Query(default=None, description="Filter by company UUID. Required for super_admin; ignored for admin (always scoped to their own company)."),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    List users.

    **admin**: always returns users within their own company only.
    **super_admin**: returns users for the specified ``company_id``; if omitted, returns all users
    across every company (excluding other ``super_admin`` accounts).
    """
    if current_user.role == UserRole.ADMIN:
        query = select(User).filter(User.company_id == current_user.company_id).order_by(User.username)
    else:
        if company_id:
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
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Fetch a specific user by ID.

    **admin**: user must belong to their own company.
    **super_admin**: any user.
    """
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
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Update a user's password, role, or company.

    **admin**: user must belong to their own company; cannot move user to a different company.
    **super_admin**: any user; can reassign to any company.
    Neither role may promote a user to ``super_admin``.
    """
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
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Delete a user and all their token sessions.

    **admin**: user must belong to their own company.
    **super_admin**: any user.
    Self-deletion is blocked for both roles.
    """
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
    return None

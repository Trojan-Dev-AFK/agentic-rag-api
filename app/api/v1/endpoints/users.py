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

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_or_super_admin
from app.db.models import User
from app.db.session import get_db
from app.schemas.users import UserCreate, UserResponse, UserUpdate
from app.services import users_service

router = APIRouter()


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
    return await users_service.create_user(
        user_data=user_data,
        db=db,
        current_user=current_user,
    )


@router.get("/", response_model=list[UserResponse])
async def list_users(
    company_id: str | None = Query(
        default=None,
        description="Filter by company UUID. Required for super_admin; ignored for admin (always scoped to their own company).",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    List users.

    **admin**: always returns users within their own company only.
    **super_admin**: returns users for the specified ``company_id``; if omitted, returns all users
    across every company (excluding other ``super_admin`` accounts).
    """
    return await users_service.list_users(company_id=company_id, db=db, current_user=current_user)


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
    return await users_service.get_user(user_id=user_id, db=db, current_user=current_user)


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
    return await users_service.update_user(
        user_id=user_id,
        update_data=update_data,
        db=db,
        current_user=current_user,
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
    await users_service.delete_user(user_id=user_id, db=db, current_user=current_user)
    return None

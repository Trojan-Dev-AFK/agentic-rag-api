"""Authentication endpoints — login, logout, profile, and session listing."""

from fastapi import APIRouter, Depends, Query, Request
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, oauth2_scheme, require_admin_or_super_admin
from app.db.models import User
from app.db.session import get_db
from app.schemas.auth import LogoutResponse, MeResponse, TokenResponse
from app.schemas.sessions import SessionResponse
from app.services import auth_service

router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={
        401: {"description": "Invalid username or password."},
        429: {"description": "Too many login attempts."},
    },
)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user and return a JWT token."""
    return await auth_service.login_for_access_token(
        request=request,
        username=form_data.username,
        password=form_data.password,
        db=db,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    responses={401: {"description": "Token invalid or session already revoked."}},
)
async def logout(
    token: str = Depends(oauth2_scheme),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Logout the current user and permanently revoke their token session."""
    return await auth_service.logout(token=token, current_user=current_user, db=db)


@router.get("/me", response_model=MeResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile."""
    return auth_service.get_current_user_profile(current_user=current_user)


@router.get("/me/sessions", response_model=list[SessionResponse])
async def list_my_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all token sessions for the current user."""
    return await auth_service.list_my_sessions(current_user=current_user, db=db)


@router.get("/sessions/company", response_model=list[SessionResponse])
async def list_company_sessions(
    company_id: str | None = Query(
        default=None,
        description="Filter by company UUID. Admin users are always restricted to their own company.",
    ),
    current_user: User = Depends(require_admin_or_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    List token sessions for a company.

    **admin**: sees sessions for their own company only.
    **super_admin**: can list all company sessions or filter by ``company_id``.
    """
    return await auth_service.list_company_sessions(
        company_id=company_id,
        current_user=current_user,
        db=db,
    )

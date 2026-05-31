"""Authentication endpoints — login, logout, profile, and session listing."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, oauth2_scheme
from app.core.config import settings
from app.core.logger import get_logger
from app.core.security import create_access_token, verify_password
from app.db.models import TokenSession, User
from app.db.session import get_db
from app.schemas.auth import LogoutResponse, MeResponse, TokenResponse
from app.schemas.sessions import SessionResponse

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/login",
    response_model=TokenResponse,
    responses={401: {"description": "Invalid username or password."}},
)
async def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    """Authenticate a user and return a JWT token."""
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Login attempt", extra={"username": form_data.username, "ip": client_ip})

    result = await db.execute(select(User).filter(User.username == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        logger.warning(
            "Login failed — invalid credentials",
            extra={"username": form_data.username, "ip": client_ip},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    jti = str(uuid.uuid4())
    access_token = create_access_token(
        data={
            "sub": user.username,
            "role": user.role,
            "company_id": user.company_id,
            "jti": jti,
        },
        expires_delta=access_token_expires,
    )

    token_session = TokenSession(
        user_id=user.id,
        jti=jti,
        expires_at=datetime.now(UTC) + access_token_expires,
        ip_address=client_ip,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(token_session)
    await db.commit()

    logger.info(
        "Login successful",
        extra={
            "user_id": user.id,
            "username": user.username,
            "role": str(user.role),
            "company_id": user.company_id,
            "jti": jti,
            "ip": client_ip,
        },
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=int(access_token_expires.total_seconds()),
        role=user.role,
        company_id=user.company_id,
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
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        jti = payload.get("jti")
    except JWTError as exc:
        logger.warning("Logout failed — JWT decode error", extra={"user_id": current_user.id, "reason": str(exc)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    session_result = await db.execute(
        select(TokenSession).filter(TokenSession.jti == jti, TokenSession.user_id == current_user.id)
    )
    token_session = session_result.scalar_one_or_none()
    if not token_session:
        logger.warning("Logout attempted with unknown session", extra={"user_id": current_user.id, "jti": jti})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")

    now = datetime.now(UTC)
    token_session.revoked_at = now
    token_session.logout_at = now
    await db.commit()

    logger.info("User logged out", extra={"user_id": current_user.id, "jti": jti})

    return LogoutResponse(message="Successfully logged out")


@router.get("/me", response_model=MeResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile."""
    logger.info("Profile fetched", extra={"user_id": current_user.id, "username": current_user.username})
    return MeResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        company_id=current_user.company_id,
        company_name=current_user.company.name if current_user.company else None,
        created_at=current_user.created_at,
    )


@router.get("/me/sessions", response_model=list[SessionResponse])
async def list_my_sessions(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all token sessions for the current user."""
    result = await db.execute(
        select(TokenSession).filter(TokenSession.user_id == current_user.id).order_by(TokenSession.issued_at.desc())
    )
    sessions = result.scalars().all()
    logger.info(
        "Sessions listed",
        extra={"user_id": current_user.id, "session_count": len(sessions)},
    )
    return sessions

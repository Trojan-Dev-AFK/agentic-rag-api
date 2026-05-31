from datetime import datetime, timedelta, timezone
from typing import List
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from jose import jwt, JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin, get_current_user, oauth2_scheme
from app.core.config import settings
from app.core.security import (
    verify_password,
    create_access_token
)
from app.db.models import User, TokenSession
from app.db.session import get_db
from app.schemas.auth import TokenResponse, LogoutResponse, MeResponse
from app.schemas.sessions import SessionResponse

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login_for_access_token(
        form_data: OAuth2PasswordRequestForm = Depends(),
        db: AsyncSession = Depends(get_db)
):
    """Authenticate a user and return a JWT token."""
    result = await db.execute(select(User).filter(User.username == form_data.username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
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
        expires_delta=access_token_expires
    )

    token_session = TokenSession(
        user_id=user.id,
        jti=jti,
        expires_at=datetime.now(timezone.utc) + access_token_expires,
    )
    db.add(token_session)
    await db.commit()

    return TokenResponse(
        access_token=access_token,
        expires_in=int(access_token_expires.total_seconds()),
        role=user.role,
        company_id=user.company_id,
    )


@router.post("/logout", response_model=LogoutResponse)
async def logout(
        token: str = Depends(oauth2_scheme),
        current_user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db)
):
    """Logout the current user and revoke their token session."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        jti = payload.get("jti")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    session_result = await db.execute(
        select(TokenSession).filter(TokenSession.jti == jti, TokenSession.user_id == current_user.id)
    )
    token_session = session_result.scalar_one_or_none()
    if not token_session:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found")

    token_session.revoked_at = datetime.now(timezone.utc)
    token_session.logout_at = datetime.now(timezone.utc)
    await db.commit()

    return LogoutResponse(message="Successfully logged out")


@router.get("/me", response_model=MeResponse)
async def get_current_user_profile(current_user: User = Depends(get_current_user)):
    """Get the current user's profile."""
    return MeResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        company_id=current_user.company_id,
        company_name=current_user.company.name if current_user.company else None,
        created_at=current_user.created_at,
    )


@router.get("/me/sessions", response_model=List[SessionResponse])
async def list_my_sessions(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all active token sessions for the current user."""
    result = await db.execute(
        select(TokenSession).filter(TokenSession.user_id == current_user.id).order_by(TokenSession.issued_at.desc())
    )
    sessions = result.scalars().all()
    return sessions

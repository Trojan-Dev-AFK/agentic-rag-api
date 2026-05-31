# FastAPI dependencies (DB sessions, auth)

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.db.session import get_db
from app.db.models import User, UserRole, TokenSession

# This tells FastAPI where the client should go to get their token
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        jti: str = payload.get("jti")
        if username is None or jti is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).filter(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_exception

    session_result = await db.execute(
        select(TokenSession).filter(TokenSession.jti == jti, TokenSession.user_id == user.id)
    )
    token_session = session_result.scalar_one_or_none()
    if (
        token_session is None
        or token_session.revoked_at is not None
        or token_session.logout_at is not None
        or token_session.expires_at < datetime.now(timezone.utc)
    ):
        raise credentials_exception

    return user


def require_company_user(current_user: User = Depends(get_current_user)):
    """Allows ADMIN and EMPLOYEE. Blocks SUPER_ADMIN (they have no company)."""
    if current_user.role == UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


def require_super_admin(current_user: User = Depends(get_current_user)):
    if current_user.role != UserRole.SUPER_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)):
    """Company-scoped admin. Must have ADMIN role and belong to a company."""
    if current_user.role != UserRole.ADMIN or current_user.company_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user

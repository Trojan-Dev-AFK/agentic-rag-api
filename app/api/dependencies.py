"""
FastAPI dependencies for authentication and role-based access control.

Every protected endpoint declares one of these as a ``Depends()`` parameter:

- ``get_current_user``          — decodes the JWT and validates the TokenSession row.
- ``require_company_user``      — blocks ``super_admin``; allows ``admin`` and ``employee``.
- ``require_super_admin``       — allows ``super_admin`` only.
- ``require_admin``             — allows company-scoped ``admin`` only (must have ``company_id``).
- ``require_admin_or_super_admin`` — allows ``super_admin`` (any company) and ``admin``
                                     (own company). Blocks ``employee``.
"""

from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.core.runtime_controls import token_session_cache_get, token_session_cache_set
from app.db.models import TokenSession, User, UserRole
from app.db.session import get_db

logger = get_logger(__name__)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")


async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)):
    """Decode the JWT, validate the token session row, and return the authenticated user."""
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
            logger.warning("JWT missing 'sub' or 'jti' claim")
            raise credentials_exception
    except JWTError as exc:
        logger.warning("JWT decode failed", extra={"reason": str(exc)})
        raise credentials_exception from exc

    result = await db.execute(select(User).filter(User.username == username))
    user = result.scalar_one_or_none()
    if user is None:
        logger.warning("JWT references unknown user", extra={"username": username})
        raise credentials_exception

    cached_user_id = await token_session_cache_get(jti=jti)
    if cached_user_id == user.id:
        return user

    session_result = await db.execute(
        select(TokenSession).filter(TokenSession.jti == jti, TokenSession.user_id == user.id)
    )
    token_session = session_result.scalar_one_or_none()

    if token_session is None:
        logger.warning("Token session not found", extra={"user_id": user.id, "jti": jti})
        raise credentials_exception
    if token_session.revoked_at is not None:
        logger.warning("Attempt to use revoked token", extra={"user_id": user.id, "jti": jti})
        raise credentials_exception
    if token_session.logout_at is not None:
        logger.warning("Attempt to use logged-out token", extra={"user_id": user.id, "jti": jti})
        raise credentials_exception
    if token_session.expires_at < datetime.now(UTC):
        logger.warning("Attempt to use expired token", extra={"user_id": user.id, "jti": jti})
        raise credentials_exception

    remaining_seconds = int((token_session.expires_at - datetime.now(UTC)).total_seconds())
    ttl_seconds = max(1, min(settings.TOKEN_SESSION_CACHE_TTL_SECONDS, remaining_seconds))
    await token_session_cache_set(jti=jti, user_id=user.id, ttl_seconds=ttl_seconds)

    return user


def require_company_user(current_user: User = Depends(get_current_user)):
    """Allow ``admin`` and ``employee``. Block ``super_admin`` (they have no company)."""
    if current_user.role == UserRole.SUPER_ADMIN:
        logger.warning(
            "Super admin attempted to access company-only endpoint",
            extra={"user_id": current_user.id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


def require_super_admin(current_user: User = Depends(get_current_user)):
    """Allow ``super_admin`` only."""
    if current_user.role != UserRole.SUPER_ADMIN:
        logger.warning(
            "Non-super-admin attempted super-admin endpoint",
            extra={"user_id": current_user.id, "role": current_user.role},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


def require_admin(current_user: User = Depends(get_current_user)):
    """Allow company-scoped ``admin`` only. Must have ``ADMIN`` role and a ``company_id``."""
    if current_user.role != UserRole.ADMIN or current_user.company_id is None:
        logger.warning(
            "Insufficient role for admin endpoint",
            extra={"user_id": current_user.id, "role": current_user.role},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user


def require_admin_or_super_admin(current_user: User = Depends(get_current_user)):
    """
    Allow ``super_admin`` (platform-wide access) and company ``admin`` (own company only).

    Blocks ``employee``. Used on user-management endpoints where ``super_admin``
    needs cross-company access to bootstrap the first admin for each company.
    """
    if current_user.role == UserRole.EMPLOYEE:
        logger.warning(
            "Employee attempted user-management endpoint",
            extra={"user_id": current_user.id},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to perform this action.",
        )
    return current_user

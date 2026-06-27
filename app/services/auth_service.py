"""Business logic for authentication and session-management operations."""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logger import get_logger
from app.core.runtime_controls import rate_limit_exceeded, token_session_cache_delete
from app.core.security import create_access_token, verify_password
from app.db.models import TokenSession, User, UserRole
from app.schemas.auth import LogoutResponse, MeResponse, TokenResponse

logger = get_logger(__name__)


async def login_for_access_token(*, request: Request, username: str, password: str, db: AsyncSession) -> TokenResponse:
    """Authenticate user credentials and create a JWT plus persistent token session."""
    client_ip = request.client.host if request.client else "unknown"
    logger.info("Login attempt", extra={"username": username, "ip": client_ip})

    login_limit_key = f"rl:login:{client_ip}:{username.strip().lower()}"
    if await rate_limit_exceeded(
        key=login_limit_key,
        limit=settings.LOGIN_RATE_LIMIT_ATTEMPTS,
        window_seconds=settings.LOGIN_RATE_LIMIT_WINDOW_SECONDS,
    ):
        logger.warning("Login throttled by rate limiter", extra={"username": username, "ip": client_ip})
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")

    result = await db.execute(select(User).filter(User.username == username))
    user = result.scalar_one_or_none()

    if not user or not verify_password(password, user.hashed_password):
        logger.warning(
            "Login failed — invalid credentials",
            extra={"username": username, "ip": client_ip},
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


async def logout(*, token: str, current_user: User, db: AsyncSession) -> LogoutResponse:
    """Revoke the current token session and mark it as logged out."""
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
    await token_session_cache_delete(jti=jti)

    logger.info("User logged out", extra={"user_id": current_user.id, "jti": jti})
    return LogoutResponse(message="Successfully logged out")


def get_current_user_profile(*, current_user: User) -> MeResponse:
    """Convert the authenticated ORM user into API profile response."""
    logger.info("Profile fetched", extra={"user_id": current_user.id, "username": current_user.username})
    return MeResponse(
        id=current_user.id,
        username=current_user.username,
        role=current_user.role,
        company_id=current_user.company_id,
        company_name=current_user.company.name if current_user.company else None,
        created_at=current_user.created_at,
    )


async def list_my_sessions(*, current_user: User, db: AsyncSession) -> list[TokenSession]:
    """List all token sessions for the authenticated user."""
    result = await db.execute(
        select(TokenSession).filter(TokenSession.user_id == current_user.id).order_by(TokenSession.issued_at.desc())
    )
    sessions = result.scalars().all()
    logger.info(
        "Sessions listed",
        extra={"user_id": current_user.id, "session_count": len(sessions)},
    )
    return list(sessions)


async def list_company_sessions(*, company_id: str | None, current_user: User, db: AsyncSession) -> list[TokenSession]:
    """List sessions company-scoped for admins or globally/filtered for super admins."""
    target_company_id = company_id
    if current_user.role == UserRole.ADMIN:
        if company_id and company_id != current_user.company_id:
            logger.warning(
                "Company sessions access denied",
                extra={
                    "user_id": current_user.id,
                    "actor_company": current_user.company_id,
                    "requested_company": company_id,
                },
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        target_company_id = current_user.company_id

    stmt = select(TokenSession).join(User, User.id == TokenSession.user_id)

    if target_company_id:
        stmt = stmt.where(User.company_id == target_company_id)
    else:
        stmt = stmt.where(User.company_id.is_not(None))

    stmt = stmt.order_by(TokenSession.issued_at.desc())
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    logger.info(
        "Company sessions listed",
        extra={
            "actor": current_user.id,
            "actor_role": str(current_user.role),
            "target_company_id": target_company_id or "all_companies",
            "session_count": len(sessions),
        },
    )
    return list(sessions)

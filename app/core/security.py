"""
JWT creation and bcrypt password utilities.

All cryptographic operations are centralised here so that the rest of the
application never handles raw secrets or hashing logic directly.
"""

import uuid
from datetime import UTC, datetime, timedelta

import bcrypt
from jose import jwt

from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Check if a plain-text password matches its stored bcrypt hash.

    Returns ``False`` (never raises) if the hash is malformed or the check fails,
    so callers can treat the return value as a plain boolean.

    Args:
        plain_password: Raw password from the login request.
        hashed_password: Bcrypt digest stored in the database.

    Returns:
        ``True`` if the password matches, ``False`` otherwise.
    """
    try:
        return bcrypt.checkpw(
            plain_password.encode(settings.ENCODING),
            hashed_password.encode(settings.ENCODING),
        )
    except Exception:
        return False


def get_password_hash(password: str) -> str:
    """Hash ``password`` with bcrypt (auto-generated salt) and return the digest as a string."""
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(password.encode(settings.ENCODING), salt)
    return hashed_bytes.decode(settings.ENCODING)


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Mint a signed JWT containing ``data`` plus ``exp`` and ``jti`` claims.

    A ``jti`` is injected automatically unless already present in ``data``.

    Args:
        data: Claims to embed in the payload (e.g. ``sub``, ``role``, ``company_id``).
        expires_delta: Token lifetime override. Defaults to
            ``ACCESS_TOKEN_EXPIRE_MINUTES`` from settings.

    Returns:
        Encoded JWT string.
    """
    to_encode = data.copy()
    expire = datetime.now(UTC) + (
        expires_delta if expires_delta else timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)

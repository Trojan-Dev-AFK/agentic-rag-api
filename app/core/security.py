import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt
import bcrypt

from app.core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against its hashed database counterpart."""
    try:
        # bcrypt requires bytes, so we encode the strings to utf-8 first
        return bcrypt.checkpw(
            plain_password.encode(settings.ENCODING),
            hashed_password.encode(settings.ENCODING)
        )
    except Exception:
        # If the hash is malformed or invalid, fail safely
        return False


def get_password_hash(password: str) -> str:
    """Securely hash a password using a randomly generated salt."""
    # gensalt() automatically handles work factor calibration
    salt = bcrypt.gensalt()

    # Hash the password (must be bytes)
    hashed_bytes = bcrypt.hashpw(password.encode(settings.ENCODING), salt)

    # Decode back to a string so it can be saved in PostgreSQL easily
    return hashed_bytes.decode(settings.ENCODING)


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Generate a signed JWT access token with a unique token identifier."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"exp": expire})
    if "jti" not in to_encode:
        to_encode["jti"] = str(uuid.uuid4())

    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt

from datetime import datetime, timedelta
from typing import Optional
from jose import jwt
import bcrypt

# In production, this goes in your .env file!
SECRET_KEY = "super-secret-development-key-do-not-use-in-prod"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against its hashed database counterpart."""
    try:
        # bcrypt requires bytes, so we encode the strings to utf-8 first
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8")
        )
    except Exception:
        # If the hash is malformed or invalid, fail safely
        return False


def get_password_hash(password: str) -> str:
    """Securely hash a password using a randomly generated salt."""
    # gensalt() automatically handles work factor calibration
    salt = bcrypt.gensalt()

    # Hash the password (must be bytes)
    hashed_bytes = bcrypt.hashpw(password.encode("utf-8"), salt)

    # Decode back to a string so it can be saved in PostgreSQL easily
    return hashed_bytes.decode("utf-8")


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Generate a signed JWT access token."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

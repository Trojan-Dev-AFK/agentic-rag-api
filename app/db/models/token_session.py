"""TokenSession ORM model — enables JWT revocation."""

import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class TokenSession(Base):
    """
    Tracks every issued JWT token by its unique ``jti`` (JWT ID) claim.

    Stateless JWTs cannot be revoked by themselves. By persisting the ``jti``
    in this table, the auth guard can reject tokens whose session row has been
    revoked or logged out, providing hard logout semantics without requiring
    short-lived tokens.

    A token is considered invalid if any of the following is true:
    - The row does not exist.
    - ``revoked_at`` is set.
    - ``logout_at`` is set.
    - ``expires_at`` is in the past.

    Cascade rules:
    - Deleting a user cascades to all their token sessions.
    """

    __tablename__ = "token_sessions"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    jti = Column(String, unique=True, index=True, nullable=False)
    issued_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    logout_at = Column(DateTime(timezone=True), nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)

    user = relationship("User", back_populates="sessions")

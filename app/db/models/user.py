"""User ORM model and UserRole enumeration."""

import enum
import uuid

from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class UserRole(enum.StrEnum):
    """
    RBAC roles in order of decreasing platform scope.

    - ``super_admin``: Platform operator. No company affiliation. Manages companies only.
    - ``admin``: Company administrator. Manages users and documents within one company; can use chat.
    - ``employee``: Standard company user. Chat access only.
    """

    SUPER_ADMIN = "super_admin"
    ADMIN = "admin"
    EMPLOYEE = "employee"


class User(Base):
    """
    An application user.

    ``company_id`` is ``NULL`` for ``super_admin`` accounts and set for ``admin`` / ``employee``.
    The password is never stored in plain text — only the bcrypt hash.

    Cascade rules:
    - Deleting a user cascades to all their token sessions.
    - Deleting the parent company sets ``company_id`` to NULL (SET NULL).
    """

    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.EMPLOYEE, nullable=False)
    company_id = Column(String, ForeignKey("companies.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="users")
    sessions = relationship("TokenSession", back_populates="user", cascade="all, delete-orphan")

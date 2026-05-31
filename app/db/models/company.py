"""Company ORM model — the top-level tenant entity."""

import uuid

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.orm import relationship

from app.db.models.base import Base


class Company(Base):
    """
    A tenant company. Every user and document belongs to exactly one company.

    Cascade rules:
    - Deleting a company cascades to all its users, documents, and document chunks.
    """

    __tablename__ = "companies"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, unique=True, index=True, nullable=False)
    industry = Column(String, nullable=True)
    description = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    users = relationship("User", back_populates="company", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="company", cascade="all, delete-orphan")

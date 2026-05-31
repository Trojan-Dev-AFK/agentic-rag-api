import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Enum, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship

from app.db.models.base import Base, ProcessingStatus


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    company_id = Column(String, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"))
    text_content = Column(String, nullable=False)
    embedding = Column(Vector(384))

    document = relationship("Document", back_populates="chunks")

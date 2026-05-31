"""Document and DocumentChunk ORM models."""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import relationship

from app.db.models.base import Base, ProcessingStatus


class Document(Base):
    """
    Metadata record for a PDF uploaded by a company admin.

    The actual file lives in the configured storage backend (local or S3).
    Once the Celery worker finishes ingestion the file is deleted and only
    the text chunks + embeddings remain in the database.

    Cascade rules:
    - Deleting a document cascades to all its ``DocumentChunk`` rows (pgvector embeddings).
    - Deleting the parent company cascades to this document too.
    """

    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    company_id = Column(String, ForeignKey("companies.id", ondelete="CASCADE"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    company = relationship("Company", back_populates="documents")
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")


class DocumentChunk(Base):
    """
    A single text chunk extracted from a ``Document``, with its pgvector embedding.

    The embedding is a 384-dimensional float vector produced by the
    ``all-MiniLM-L6-v2`` sentence-transformers model. Cosine distance search
    against this column powers the ``search_documents`` agent tool.
    """

    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"))
    text_content = Column(String, nullable=False)
    embedding = Column(Vector(384))

    document = relationship("Document", back_populates="chunks")

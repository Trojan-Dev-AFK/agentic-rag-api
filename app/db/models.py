# SQLAlchemy declarative base models
import enum
import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, String, Enum, DateTime, func, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class ProcessingStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    filename = Column(String, nullable=False)
    status = Column(Enum(ProcessingStatus), default=ProcessingStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationship to the chunks
    chunks = relationship("DocumentChunk", back_populates="document", cascade="all, delete-orphan")

class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id = Column(String, ForeignKey("documents.id", ondelete="CASCADE"))

    # The actual text from the PDF
    text_content = Column(String, nullable=False)

    # The vector representation.
    embedding = Column(Vector(384))

    document = relationship("Document", back_populates="chunks")

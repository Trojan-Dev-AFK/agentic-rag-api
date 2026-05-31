"""SQLAlchemy declarative base and shared enumerations."""

import enum

from sqlalchemy.orm import declarative_base

Base = declarative_base()


class ProcessingStatus(enum.StrEnum):
    """Lifecycle states of a PDF document through the Celery ingestion pipeline."""

    PENDING = "PENDING"
    """Document row created; worker task queued but not yet started."""

    PROCESSING = "PROCESSING"
    """Worker is actively reading, chunking, and embedding the PDF."""

    COMPLETED = "COMPLETED"
    """All chunks have been embedded and stored; the file has been deleted from storage."""

    FAILED = "FAILED"
    """An unrecoverable error occurred during ingestion. The document row is retained for audit."""

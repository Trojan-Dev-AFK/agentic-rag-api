"""
Abstract storage backend interface and shared filename helper.
"""

import re
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path

from fastapi import UploadFile


def _storage_filename(filename: str, created_at: datetime) -> str:
    """
    Build a storage filename from the original name and a UTC timestamp.

    Example:
        'Q3 Report.pdf' at 2026-05-31 14:30:45 → 'Q3_Report_31-05-2026_14-30-45.pdf'
    """
    stem = Path(filename).stem
    stem = re.sub(r"[^\w\-]", "_", stem).strip("_")
    ts = created_at.strftime("%d-%m-%Y_%H-%M-%S")
    return f"{stem}_{ts}.pdf"


class StorageBackend(ABC):
    """
    Abstract interface for document file storage.

    Implement this to add a new storage backend — the rest of the application
    only calls ``upload``, ``build_ref``, ``get_local_path``, and ``delete``.
    """

    @abstractmethod
    async def upload(
        self,
        file: UploadFile,
        company_id: str,
        doc_id: str,
        filename: str,
        created_at: datetime,
    ) -> str:
        """Save the file and return a storage reference (local path or S3 key)."""

    @abstractmethod
    def build_ref(self, company_id: str, doc_id: str, filename: str, created_at: datetime) -> str:
        """Reconstruct the storage reference from document metadata (no I/O)."""

    @abstractmethod
    def get_local_path(self, storage_ref: str) -> str:
        """
        Return a local filesystem path ready for reading.

        For ``LocalStorage``: returns ``storage_ref`` unchanged.
        For ``S3Storage``: downloads the object to a temp file and returns that path.
        """

    @abstractmethod
    def delete(self, storage_ref: str) -> None:
        """Delete the stored file. No-op if it no longer exists."""

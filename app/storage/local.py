import os
from datetime import datetime

from fastapi import UploadFile

from app.core.config import settings
from app.core.logger import get_logger
from app.storage.base import StorageBackend, _storage_filename

logger = get_logger(__name__)


class LocalStorage(StorageBackend):
    """Stores uploaded documents on the local filesystem under ``LOCAL_UPLOAD_DIR``."""

    def __init__(self):
        self._upload_dir = settings.LOCAL_UPLOAD_DIR

    async def upload(self, file: UploadFile, company_id: str, doc_id: str, filename: str, created_at: datetime) -> str:
        """Write ``file`` to ``{upload_dir}/{company_id}/{stem}_{timestamp}.pdf`` and return the path."""
        company_dir = os.path.join(self._upload_dir, company_id)
        os.makedirs(company_dir, exist_ok=True)
        file_path = self.build_ref(company_id, doc_id, filename, created_at)

        logger.info("Writing file to local storage", extra={"company_id": company_id, "path": file_path})
        try:
            total_bytes = 0
            with open(file_path, "wb") as f:
                while True:
                    chunk = await file.read(1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    total_bytes += len(chunk)
        except OSError as exc:
            logger.error("Local file write failed", extra={"path": file_path}, exc_info=exc)
            raise
        finally:
            await file.seek(0)

        logger.info(
            "File written to local storage",
            extra={"company_id": company_id, "path": file_path, "bytes": total_bytes},
        )
        return file_path

    def build_ref(self, company_id: str, doc_id: str, filename: str, created_at: datetime) -> str:
        """Return the absolute file path for this document without touching the filesystem."""
        return os.path.join(self._upload_dir, company_id, _storage_filename(filename, created_at))

    def get_local_path(self, storage_ref: str) -> str:
        """Return ``storage_ref`` unchanged — the file is already on the local filesystem."""
        return storage_ref

    def delete(self, storage_ref: str) -> None:
        """Delete the file at ``storage_ref`` if it exists; silently skip if already gone."""
        if os.path.exists(storage_ref):
            try:
                os.remove(storage_ref)
                logger.info("Local file deleted", extra={"path": storage_ref})
            except OSError as exc:
                logger.error("Local file delete failed", extra={"path": storage_ref}, exc_info=exc)
                raise
        else:
            logger.debug("Local file already absent — skipping delete", extra={"path": storage_ref})

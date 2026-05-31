"""
Storage backend factory.

Call ``get_storage()`` to obtain the appropriate ``StorageBackend`` implementation
based on the ``DOCUMENT_STORAGE`` environment variable:

- ``LOCAL``         → ``LocalStorage``  — writes to ``LOCAL_UPLOAD_DIR/``
- ``CLOUD_STORAGE`` → ``S3Storage``     — writes to ``s3://{S3_BUCKET_NAME}/BACKEND/``

The backend is a **process-level singleton**: the first call constructs it
(which for S3 creates the boto3 client and its connection pool), and every
subsequent call in the same process returns the same object.
"""

from app.core.config import settings
from app.storage.base import StorageBackend

_storage: StorageBackend | None = None


def get_storage() -> StorageBackend:
    """Return the process-level storage backend, constructing it on first call."""
    global _storage
    if _storage is None:
        if settings.DOCUMENT_STORAGE == "CLOUD_STORAGE":
            from app.storage.s3 import S3Storage

            _storage = S3Storage()
        else:
            from app.storage.local import LocalStorage

            _storage = LocalStorage()
    return _storage

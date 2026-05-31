import asyncio
import os
import tempfile
from datetime import datetime

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import UploadFile

from app.core.config import settings
from app.core.logger import get_logger
from app.storage.base import StorageBackend, _storage_filename

logger = get_logger(__name__)

_PREFIX = "BACKEND"


class S3Storage(StorageBackend):
    """Stores uploaded documents in AWS S3 under ``BACKEND/{company_id}/``."""

    def __init__(self):
        """Initialise a boto3 S3 client using credentials from application settings."""
        self._bucket = settings.S3_BUCKET_NAME
        self._client = boto3.client(
            "s3",
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
            region_name=settings.AWS_REGION,
        )
        logger.info(
            "S3Storage initialised",
            extra={"bucket": self._bucket, "region": settings.AWS_REGION},
        )

    async def upload(self, file: UploadFile, company_id: str, doc_id: str, filename: str, created_at: datetime) -> str:
        """Stream ``file`` to S3 at ``BACKEND/{company_id}/{stem}_{timestamp}.pdf`` and return the key."""
        key = self.build_ref(company_id, doc_id, filename, created_at)
        logger.info(
            "Uploading file to S3",
            extra={"bucket": self._bucket, "key": key, "company_id": company_id},
        )
        try:
            await asyncio.to_thread(
                self._client.upload_fileobj,
                file.file,
                self._bucket,
                key,
            )
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "S3 upload failed",
                extra={"bucket": self._bucket, "key": key},
                exc_info=exc,
            )
            raise

        logger.info("S3 upload complete", extra={"bucket": self._bucket, "key": key})
        return key

    def build_ref(self, company_id: str, doc_id: str, filename: str, created_at: datetime) -> str:
        """Return the S3 object key for this document without making any API call."""
        return f"{_PREFIX}/{company_id}/{_storage_filename(filename, created_at)}"

    def get_local_path(self, storage_ref: str) -> str:
        """Download the S3 object to a temp file and return its local path."""
        stored_filename = storage_ref.rsplit("/", 1)[-1]
        tmp_path = os.path.join(tempfile.gettempdir(), stored_filename)
        logger.info(
            "Downloading file from S3",
            extra={"bucket": self._bucket, "key": storage_ref, "dest": tmp_path},
        )
        try:
            self._client.download_file(self._bucket, storage_ref, tmp_path)
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "S3 download failed",
                extra={"bucket": self._bucket, "key": storage_ref},
                exc_info=exc,
            )
            raise

        logger.info("S3 download complete", extra={"key": storage_ref, "dest": tmp_path})
        return tmp_path

    def delete(self, storage_ref: str) -> None:
        """Delete the S3 object at ``storage_ref``. Idempotent — no error if already absent."""
        logger.info("Deleting S3 object", extra={"bucket": self._bucket, "key": storage_ref})
        try:
            # delete_object is idempotent — no error if key does not exist
            self._client.delete_object(Bucket=self._bucket, Key=storage_ref)
            logger.info("S3 object deleted", extra={"bucket": self._bucket, "key": storage_ref})
        except (BotoCoreError, ClientError) as exc:
            logger.error(
                "S3 delete failed",
                extra={"bucket": self._bucket, "key": storage_ref},
                exc_info=exc,
            )
            raise

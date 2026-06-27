"""Business logic for document upload, listing, retrieval, and deletion."""

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import StorageError
from app.core.logger import get_logger
from app.core.runtime_controls import cache_delete_prefix, cache_get_json, cache_set_json
from app.db.models import Document, User, UserRole
from app.schemas.documents import DocumentResponse, UploadResponse
from app.services.common import get_by_id_or_404, get_company_or_400, sanitize_pagination
from app.storage import get_storage

logger = get_logger(__name__)

def _list_cache_key(*, current_user: User, company_id: str | None) -> str:
    if current_user.role == UserRole.ADMIN:
        return f"cache:docs:list:admin:{current_user.company_id}"
    if company_id:
        return f"cache:docs:list:superadmin:company:{company_id}"
    return "cache:docs:list:superadmin:all"


def _get_cache_key(*, document_id: str) -> str:
    return f"cache:docs:get:{document_id}"


async def _invalidate_document_caches(*, company_id: str | None, document_id: str | None = None) -> None:
    if company_id:
        await cache_delete_prefix(prefix=f"cache:docs:list:admin:{company_id}")
        await cache_delete_prefix(prefix=f"cache:docs:list:superadmin:company:{company_id}")
        await cache_delete_prefix(prefix=f"cache:vector:{company_id}:")
    await cache_delete_prefix(prefix="cache:docs:list:superadmin:all")
    if document_id:
        await cache_delete_prefix(prefix=_get_cache_key(document_id=document_id))


async def _assert_pdf_upload(file: UploadFile) -> None:
    """Validate that the uploaded payload is a PDF by extension and file signature."""
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file must have a filename")

    # Prefer strict extension checks so users receive immediate feedback.
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only PDF files are supported")

    header = await file.read(5)
    await file.seek(0)
    if header != b"%PDF-":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is not a valid PDF")

    file.file.seek(0, 2)
    file_size = file.file.tell()
    file.file.seek(0)
    if file_size > settings.MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum allowed size is {settings.MAX_UPLOAD_BYTES} bytes.",
        )


def _to_document_response(document: Document) -> DocumentResponse:
    """Map ORM document model to API response object."""
    return DocumentResponse(
        id=document.id,
        filename=document.filename,
        status=document.status,
        created_at=document.created_at,
    )


async def upload_document(
    *,
    file: UploadFile,
    company_id: str | None,
    db: AsyncSession,
    current_user: User,
) -> UploadResponse:
    """Create document record, upload file to storage, and enqueue processing task."""
    await _assert_pdf_upload(file)

    if current_user.role == UserRole.ADMIN:
        target_company_id = current_user.company_id
    else:
        if not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="company_id is required for super_admin uploads"
            )

        await get_company_or_400(db=db, company_id=company_id, actor_id=current_user.id)

        target_company_id = company_id

    logger.info(
        "Document upload received",
        extra={
            "file_name": file.filename,
            "content_type": file.content_type,
            "target_company_id": target_company_id,
            "actor": current_user.id,
            "actor_role": str(current_user.role),
        },
    )

    new_doc = Document(filename=file.filename, company_id=target_company_id)
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    logger.info("Document record created", extra={"doc_id": new_doc.id, "company_id": target_company_id})

    try:
        storage = get_storage()
        storage_ref = await storage.upload(
            file,
            target_company_id,
            new_doc.id,
            new_doc.filename,
            new_doc.created_at,
        )
    except Exception as exc:
        logger.error(
            "File storage failed — rolling back document record",
            extra={"doc_id": new_doc.id, "company_id": target_company_id},
            exc_info=exc,
        )
        await db.delete(new_doc)
        await db.commit()
        raise StorageError("Failed to store the uploaded file. Please try again.") from exc

    logger.info(
        "File stored successfully",
        extra={"doc_id": new_doc.id, "storage_ref": storage_ref},
    )

    from app.worker.tasks import process_pdf_task

    process_pdf_task.delay(new_doc.id, storage_ref)
    logger.info("Processing task dispatched", extra={"doc_id": new_doc.id})

    await _invalidate_document_caches(company_id=target_company_id, document_id=new_doc.id)

    return UploadResponse(
        message="Document accepted for processing",
        document_id=new_doc.id,
        status=new_doc.status,
    )


async def list_documents(
    *,
    company_id: str | None,
    limit: int | None = None,
    offset: int | None = None,
    db: AsyncSession,
    current_user: User,
) -> list[DocumentResponse]:
    """List documents with company scoping based on actor role."""
    safe_limit, safe_offset = sanitize_pagination(limit=limit, offset=offset)
    cache_key = f"{_list_cache_key(current_user=current_user, company_id=company_id)}:{safe_limit}:{safe_offset}"
    cached = await cache_get_json(key=cache_key)
    if isinstance(cached, list):
        try:
            return [DocumentResponse(**item) for item in cached if isinstance(item, dict)]
        except Exception as exc:
            logger.warning(
                "Documents list cache payload invalid — bypassing cache", extra={"key": cache_key}, exc_info=exc
            )

    if current_user.role == UserRole.ADMIN:
        query = (
            select(Document)
            .filter(Document.company_id == current_user.company_id)
            .order_by(Document.created_at.desc())
            .offset(safe_offset)
            .limit(safe_limit)
        )
    elif company_id:
        query = select(Document).filter(Document.company_id == company_id).order_by(Document.created_at.desc())
        query = query.offset(safe_offset).limit(safe_limit)
    else:
        query = select(Document).order_by(Document.created_at.desc()).offset(safe_offset).limit(safe_limit)

    result = await db.execute(query)
    docs = result.scalars().all()

    logger.info(
        "Documents listed",
        extra={
            "count": len(docs),
            "actor": current_user.id,
            "actor_role": str(current_user.role),
            "filter_company": company_id or (current_user.company_id if current_user.role == UserRole.ADMIN else "all"),
        },
    )
    response_rows = [_to_document_response(doc) for doc in docs]
    await cache_set_json(
        key=cache_key,
        payload=[item.model_dump(mode="json") for item in response_rows],
        ttl_seconds=settings.DOCUMENT_METADATA_CACHE_TTL_SECONDS,
    )
    return response_rows


async def get_document(*, document_id: str, db: AsyncSession, current_user: User) -> DocumentResponse:
    """Fetch one document by UUID with role-aware access control."""
    cache_key = _get_cache_key(document_id=document_id)
    cached = await cache_get_json(key=cache_key)
    if isinstance(cached, dict):
        cached_company_id = cached.get("company_id")
        cached_response = cached.get("response")
        if isinstance(cached_response, dict):
            if current_user.role == UserRole.ADMIN and cached_company_id != current_user.company_id:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
            return DocumentResponse(**cached_response)

    doc = await get_by_id_or_404(
        db=db,
        model=Document,
        entity_id=document_id,
        detail="Document not found",
        log_message="Document not found",
        log_extra={"doc_id": document_id, "actor": current_user.id},
    )

    if current_user.role == UserRole.ADMIN and doc.company_id != current_user.company_id:
        logger.warning(
            "Cross-company document access denied",
            extra={
                "doc_id": document_id,
                "doc_company": doc.company_id,
                "actor": current_user.id,
                "actor_company": current_user.company_id,
            },
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    logger.info("Document fetched", extra={"doc_id": document_id, "status": str(doc.status), "actor": current_user.id})
    response_row = _to_document_response(doc)
    await cache_set_json(
        key=cache_key,
        payload={"company_id": doc.company_id, "response": response_row.model_dump(mode="json")},
        ttl_seconds=settings.DOCUMENT_METADATA_CACHE_TTL_SECONDS,
    )
    return response_row


async def delete_document(*, document_id: str, db: AsyncSession, current_user: User) -> None:
    """Delete a document, associated chunks, and best-effort storage object."""
    doc = await get_by_id_or_404(
        db=db,
        model=Document,
        entity_id=document_id,
        detail="Document not found",
        log_message="Document delete failed — not found",
        log_extra={"doc_id": document_id, "actor": current_user.id},
    )

    if current_user.role == UserRole.ADMIN and doc.company_id != current_user.company_id:
        logger.warning(
            "Cross-company document delete denied",
            extra={
                "doc_id": document_id,
                "doc_company": doc.company_id,
                "actor": current_user.id,
                "actor_company": current_user.company_id,
            },
        )
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    await db.delete(doc)
    await db.commit()
    logger.warning(
        "Document deleted (cascades vector chunks)",
        extra={
            "doc_id": document_id,
            "document_filename": doc.filename,
            "company_id": doc.company_id,
            "actor": current_user.id,
        },
    )

    await _invalidate_document_caches(company_id=doc.company_id, document_id=document_id)

    try:
        storage = get_storage()
        storage_ref = storage.build_ref(doc.company_id, document_id, doc.filename, doc.created_at)
        storage.delete(storage_ref)
        logger.info("Stored file removed", extra={"doc_id": document_id, "storage_ref": storage_ref})
    except Exception as exc:
        logger.error(
            "Storage cleanup failed after document delete — file may remain in storage",
            extra={"doc_id": document_id},
            exc_info=exc,
        )

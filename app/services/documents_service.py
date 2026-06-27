"""Business logic for document upload, listing, retrieval, and deletion."""

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import StorageError
from app.core.logger import get_logger
from app.db.models import Company, Document, User, UserRole
from app.schemas.documents import DocumentResponse, UploadResponse
from app.storage import get_storage
from app.worker.tasks import process_pdf_task

logger = get_logger(__name__)


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
    if current_user.role == UserRole.ADMIN:
        target_company_id = current_user.company_id
    else:
        if not company_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="company_id is required for super_admin uploads"
            )

        company_result = await db.execute(select(Company).filter(Company.id == company_id))
        company = company_result.scalar_one_or_none()
        if not company:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Company not found")

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

    process_pdf_task.delay(new_doc.id, storage_ref)
    logger.info("Processing task dispatched", extra={"doc_id": new_doc.id})

    return UploadResponse(
        message="Document accepted for processing",
        document_id=new_doc.id,
        status=new_doc.status,
    )


async def list_documents(*, company_id: str | None, db: AsyncSession, current_user: User) -> list[DocumentResponse]:
    """List documents with company scoping based on actor role."""
    if current_user.role == UserRole.ADMIN:
        query = (
            select(Document).filter(Document.company_id == current_user.company_id).order_by(Document.created_at.desc())
        )
    elif company_id:
        query = select(Document).filter(Document.company_id == company_id).order_by(Document.created_at.desc())
    else:
        query = select(Document).order_by(Document.created_at.desc())

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
    return [_to_document_response(doc) for doc in docs]


async def get_document(*, document_id: str, db: AsyncSession, current_user: User) -> DocumentResponse:
    """Fetch one document by UUID with role-aware access control."""
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        logger.warning("Document not found", extra={"doc_id": document_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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
    return _to_document_response(doc)


async def delete_document(*, document_id: str, db: AsyncSession, current_user: User) -> None:
    """Delete a document, associated chunks, and best-effort storage object."""
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        logger.warning("Document delete failed — not found", extra={"doc_id": document_id, "actor": current_user.id})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

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
        extra={"doc_id": document_id, "filename": doc.filename, "company_id": doc.company_id, "actor": current_user.id},
    )

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

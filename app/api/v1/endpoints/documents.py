from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import require_admin_or_super_admin
from app.core.exceptions import StorageError
from app.core.logger import get_logger
from app.db.models import Document, User, UserRole
from app.db.session import get_db
from app.schemas.documents import DocumentResponse, UploadResponse
from app.storage import get_storage
from app.worker.tasks import process_pdf_task

logger = get_logger(__name__)
router = APIRouter()


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=202,
    responses={
        400: {"description": "Company not found."},
        403: {"description": "Forbidden — admin role required."},
        500: {"description": "File could not be saved to storage."},
    },
)
async def upload_document(
    file: UploadFile,
    company_id: Optional[str] = Query(
        default=None,
        description="Target company UUID. Required for super_admin; ignored for admin (always their own company).",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Upload a PDF for processing (admin/super_admin only, company-scoped).

    **admin**: always uploads to their own company.
    **super_admin**: can specify ``company_id`` to upload for any company; if omitted, uploads to a "platform" company.
    """
    if current_user.role == UserRole.ADMIN:
        target_company_id = current_user.company_id
    else:
        target_company_id = company_id or current_user.company_id

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
            file, target_company_id, new_doc.id, new_doc.filename, new_doc.created_at
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


@router.get("/", response_model=list[DocumentResponse], status_code=200)
async def list_documents(
    company_id: Optional[str] = Query(
        default=None,
        description="Filter by company UUID. Ignored for admin (always their own company); optional for super_admin.",
    ),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    List documents.

    **admin**: always returns documents from their own company only.
    **super_admin**: returns documents for the specified ``company_id``; if omitted, returns all documents.
    """
    if current_user.role == UserRole.ADMIN:
        query = select(Document).filter(Document.company_id == current_user.company_id).order_by(Document.created_at.desc())
    else:
        if company_id:
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
    return [DocumentResponse(id=d.id, filename=d.filename, status=d.status, created_at=d.created_at) for d in docs]


@router.get("/{document_id}", response_model=DocumentResponse, status_code=200)
async def get_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Check the status of a specific document.

    **admin**: must belong to their own company.
    **super_admin**: can access any document.
    """
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        logger.warning("Document not found", extra={"doc_id": document_id, "actor": current_user.id})
        raise HTTPException(status_code=404, detail="Document not found")

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
        raise HTTPException(status_code=403, detail="Access denied")

    logger.info("Document fetched", extra={"doc_id": document_id, "status": str(doc.status), "actor": current_user.id})
    return DocumentResponse(id=doc.id, filename=doc.filename, status=doc.status, created_at=doc.created_at)


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_or_super_admin),
):
    """
    Delete a document and all its vector chunks.

    **admin**: must belong to their own company.
    **super_admin**: can delete any document.
    """
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        logger.warning("Document delete failed — not found", extra={"doc_id": document_id, "actor": current_user.id})
        raise HTTPException(status_code=404, detail="Document not found")

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
        raise HTTPException(status_code=403, detail="Access denied")

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

    return None

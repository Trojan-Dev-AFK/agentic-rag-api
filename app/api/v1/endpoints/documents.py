import os
import shutil
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.dependencies import require_admin
from app.db.session import get_db
from app.db.models import Document, User
from app.worker.tasks import process_pdf_task
from app.schemas.documents import UploadResponse, DocumentResponse
from app.core.config import settings

router = APIRouter()


@router.post("/upload", response_model=UploadResponse, status_code=202)
async def upload_document(file: UploadFile, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    """Upload a PDF for processing (admin only, company-scoped)."""
    new_doc = Document(filename=file.filename, company_id=current_user.company_id)
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    file_path = os.path.join(settings.UPLOAD_DIR, f"{new_doc.id}.pdf")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    process_pdf_task.delay(new_doc.id, file_path)

    return UploadResponse(
        message="Document accepted for processing",
        document_id=new_doc.id,
        status=new_doc.status,
    )


@router.get("/", response_model=list[DocumentResponse], status_code=200)
async def list_documents(db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    """Fetch all documents in admin's company, ordered by newest first (admin only)."""
    query = (
        select(Document)
        .filter(Document.company_id == current_user.company_id)
        .order_by(Document.created_at.desc())
    )
    result = await db.execute(query)
    docs = result.scalars().all()

    return [
        DocumentResponse(
            id=doc.id,
            filename=doc.filename,
            status=doc.status,
            created_at=doc.created_at,
        ) for doc in docs
    ]


@router.get("/{document_id}", response_model=DocumentResponse, status_code=200)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    """Check the processing status of a specific document (admin only)."""
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        status=doc.status,
        created_at=doc.created_at,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_admin)):
    """Delete a document and completely wipe its AI vectors from the database (admin only)."""
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.company_id != current_user.company_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Because we set up 'ON DELETE CASCADE' in Phase 1, deleting this row
    # automatically commands Postgres to wipe all associated vector chunks!
    await db.delete(doc)
    await db.commit()

    # Housekeeping: delete the PDF file if the worker crashed before cleaning it up
    file_path = os.path.join(settings.UPLOAD_DIR, f"{document_id}.pdf")
    if os.path.exists(file_path):
        os.remove(file_path)

    return None

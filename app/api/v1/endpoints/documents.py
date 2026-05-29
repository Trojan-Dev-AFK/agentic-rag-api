import os
import shutil
from fastapi import APIRouter, UploadFile, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.api.dependencies import require_admin
from app.db.session import get_db
from app.db.models import Document
from app.worker.tasks import process_pdf_task

router = APIRouter()
UPLOAD_DIR = "uploads"


@router.post("/upload", status_code=202)
async def upload_document(file: UploadFile, db: AsyncSession = Depends(get_db)):
    # 1. Create DB record
    new_doc = Document(filename=file.filename)
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # 2. Save file temporarily
    file_path = os.path.join(UPLOAD_DIR, f"{new_doc.id}.pdf")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 3. Trigger worker
    process_pdf_task.delay(new_doc.id, file_path)

    return {
        "message": "Document accepted for processing",
        "document_id": new_doc.id,
        "status": new_doc.status
    }


@router.get("/", status_code=200)
async def list_documents(db: AsyncSession = Depends(get_db)):
    """Fetch all uploaded documents, ordered by newest first."""
    result = await db.execute(select(Document).order_by(Document.created_at.desc()))
    docs = result.scalars().all()

    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "status": doc.status,
            "created_at": doc.created_at
        } for doc in docs
    ]


@router.get("/{document_id}", status_code=200)
async def get_document(document_id: str, db: AsyncSession = Depends(get_db)):
    """Check the processing status of a specific document."""
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    return {"id": doc.id, "filename": doc.filename, "status": doc.status}


@router.delete("/{document_id}", status_code=204)
async def delete_document(document_id: str, db: AsyncSession = Depends(get_db), current_user = Depends(require_admin)):
    """Delete a document and completely wipe its AI vectors from the database."""
    result = await db.execute(select(Document).filter(Document.id == document_id))
    doc = result.scalar_one_or_none()

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Because we set up 'ON DELETE CASCADE' in Phase 1, deleting this row
    # automatically commands Postgres to wipe all associated vector chunks!
    await db.delete(doc)
    await db.commit()

    # Housekeeping: delete the PDF file if the worker crashed before cleaning it up
    file_path = os.path.join(UPLOAD_DIR, f"{document_id}.pdf")
    if os.path.exists(file_path):
        os.remove(file_path)

    return None

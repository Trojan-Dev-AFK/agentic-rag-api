import os
import shutil
from contextlib import asynccontextmanager

from fastapi import FastAPI, UploadFile, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.endpoints import chat
from app.db.models import Base, Document
from app.db.session import engine, get_db

# IMPORT YOUR CELERY TASK HERE
from app.worker.tasks import process_pdf_task

# Create an uploads directory if it doesn't exist
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)

    yield # The FastAPI application runs here

    await engine.dispose()

app = FastAPI(
    title="Agentic RAG API",
    description="Enterprise API for Document Analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# Include Chat router
app.include_router(chat.router, prefix="/v1/chat", tags=["Agent"])

@app.post("/v1/documents/upload", status_code=202)
async def upload_document(
        file: UploadFile,
        db: AsyncSession = Depends(get_db),
):
    # 1. Create the database record
    new_doc = Document(filename=file.filename)
    db.add(new_doc)
    await db.commit()
    await db.refresh(new_doc)

    # 2. Save the uploaded file temporarily to disk
    file_path = os.path.join(UPLOAD_DIR, f"{new_doc.id}.pdf")
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 3. TRIGGER THE CELERY WORKER
    # The .delay() method is what actually sends the message to Redis
    process_pdf_task.delay(new_doc.id, file_path)

    return {
        "message": "Document accepted for processing",
        "document_id": new_doc.id,
        "status": new_doc.status,
    }
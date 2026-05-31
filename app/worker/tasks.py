# Ingestion: Chunking, embedding, saving
import os

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.db.models import Document, ProcessingStatus, DocumentChunk
from app.worker.celery_app import celery_app

# Synchronous Database Setup
# Notice we use standard 'postgresql://' here, not '+asyncpg'
DATABASE_URL = settings.DATABASE_URL_SYNC
engine = create_engine(DATABASE_URL)
session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

embedding_model = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)

@celery_app.task(bind=True, name="process_pdf_task")
def process_pdf_task(self, document_id: str, file_path:str):
    db = session_local()

    # Fetch the document record we created in FastAPI
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return {"status": "error", "message": "Document not found"}

    try:
        # Step A: Update status so the user knows it started
        doc.status = ProcessingStatus.PROCESSING
        db.commit()

        # Step B: Extract raw text from the PDF
        reader = PdfReader(file_path)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)

        # Step C: Split into overlapping chunks so the AI doesn't lose context at boundaries
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
        chunks = text_splitter.split_text(full_text)

        for text_content in chunks:
            # Generate the vector array for this specific chunk
            vector = embedding_model.embed_query(text_content)

            # Create the database record
            db_chunk = DocumentChunk(
                document_id=doc.id,
                text_content=text_content,
                embedding=vector,
            )
            db.add(db_chunk)

        # Step D: Commit everything and mark as finished
        doc.status = ProcessingStatus.COMPLETED
        db.commit()

        # Housekeeping: Clean up the temporary PDF file from the disk
        if os.path.exists(file_path):
            os.remove(file_path)

        return {"status": "success", "chunks_processed": len(chunks)}

    except Exception as e:
        # If AI fails or the PDF is corrups, fail gracefully
        db.rollback()
        doc.status = ProcessingStatus.FAILED
        db.commit()
        return {"status": "failed", "error": str(e)}
    finally:
        db.close()

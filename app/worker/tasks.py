# Ingestion: Chunking, embedding, saving
import os

from langchain_community.document_loaders import PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Document, ProcessingStatus, DocumentChunk
from app.worker.celery_app import celery_app

# Synchronous Database Setup
# Notice we use standard 'postgresql://' here, not '+asyncpg'
DATABASE_URL = "postgresql://agenticraguser:agenticragpwd@localhost:5432/rag_db"
engine = create_engine(DATABASE_URL)
session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

embedding_model = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

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
        loader = PyPDFLoader(file_path)
        raw_documents = loader.load()

        # Step C: The Chunking strategy
        # We don't cut text randomly. This splitter tries to keep paragraphs
        # and sentences together so the AI doesn't lose context.
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,  # Roughly 200-250 words per chunk
            chunk_overlap=200  # 200 characters overlap to bridge concepts
        )
        chunks = text_splitter.split_documents(raw_documents)

        for chunk in chunks:
            text_content = chunk.page_content
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

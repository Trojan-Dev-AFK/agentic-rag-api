"""
Celery tasks for asynchronous PDF ingestion.

``process_pdf_task`` is the only task. It reads a PDF from storage,
splits the text into overlapping chunks, embeds each chunk with
``all-MiniLM-L6-v2``, and persists the vectors to PostgreSQL via pgvector.
"""

import os

from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.logger import get_logger, request_id_ctx
from app.db.models import Document, DocumentChunk, ProcessingStatus
from app.storage import get_storage
from app.worker.celery_app import celery_app

logger = get_logger(__name__)

engine = create_engine(settings.DATABASE_URL_SYNC)
session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# ---------------------------------------------------------------------------
# Process-level singletons — lazy-initialised on first task execution.
# FastAPI imports this module to call .delay(), but never runs the task body,
# so neither model loads in the API process.
# ---------------------------------------------------------------------------
_embedding_model: HuggingFaceEmbeddings | None = None
_text_splitter: RecursiveCharacterTextSplitter | None = None


def _get_embedding_model() -> HuggingFaceEmbeddings:
    """Return the process-level embedding model, loading it on first call."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading embedding model", extra={"model": settings.EMBEDDING_MODEL})
        _embedding_model = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
        logger.info("Embedding model loaded", extra={"model": settings.EMBEDDING_MODEL})
    return _embedding_model


def _get_text_splitter() -> RecursiveCharacterTextSplitter:
    """Return the process-level text splitter, constructing it on first call."""
    global _text_splitter
    if _text_splitter is None:
        _text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.CHUNK_SIZE,
            chunk_overlap=settings.CHUNK_OVERLAP,
        )
    return _text_splitter


@celery_app.task(bind=True, name="process_pdf_task")
def process_pdf_task(self, document_id: str, storage_ref: str):
    """
    Ingest a PDF: read → chunk → embed → persist vectors → delete source file.

    Updates ``Document.status`` throughout:
    ``PENDING`` → ``PROCESSING`` → ``COMPLETED`` (or ``FAILED`` on error).
    """
    request_id_ctx.set(f"task:{self.request.id}")

    logger.info(
        "PDF processing task started",
        extra={"doc_id": document_id, "storage_ref": storage_ref, "task_id": self.request.id},
    )

    db = session_local()
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        logger.error("Document record not found — task aborted", extra={"doc_id": document_id})
        db.close()
        return {"status": "error", "message": "Document not found"}

    storage = get_storage()
    local_path = None

    try:
        doc.status = ProcessingStatus.PROCESSING
        db.commit()
        logger.info("Status set to PROCESSING", extra={"doc_id": document_id})

        local_path = storage.get_local_path(storage_ref)
        logger.info("File available locally", extra={"doc_id": document_id, "local_path": local_path})

        reader = PdfReader(local_path)
        page_count = len(reader.pages)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        logger.info(
            "PDF read complete",
            extra={"doc_id": document_id, "pages": page_count, "chars": len(full_text)},
        )

        chunks = _get_text_splitter().split_text(full_text)
        logger.info(
            "Text split into chunks",
            extra={"doc_id": document_id, "chunk_count": len(chunks), "chunk_size": settings.CHUNK_SIZE},
        )

        embedding_model = _get_embedding_model()
        for i, text_content in enumerate(chunks):
            vector = embedding_model.embed_query(text_content)
            db.add(DocumentChunk(document_id=doc.id, text_content=text_content, embedding=vector))
            if (i + 1) % 10 == 0:
                logger.debug(
                    "Embedding progress",
                    extra={"doc_id": document_id, "embedded": i + 1, "total": len(chunks)},
                )

        doc.status = ProcessingStatus.COMPLETED
        db.commit()
        logger.info(
            "PDF processing completed",
            extra={"doc_id": document_id, "chunks_stored": len(chunks), "pages": page_count},
        )

        storage.delete(storage_ref)
        logger.info(
            "Source file removed from storage",
            extra={"doc_id": document_id, "storage_ref": storage_ref},
        )

        return {"status": "success", "chunks_processed": len(chunks)}

    except Exception as exc:
        logger.error(
            "PDF processing failed",
            extra={"doc_id": document_id, "storage_ref": storage_ref},
            exc_info=exc,
        )
        try:
            db.rollback()
            doc.status = ProcessingStatus.FAILED
            db.commit()
            logger.info("Status set to FAILED", extra={"doc_id": document_id})
        except Exception as db_exc:
            logger.critical(
                "Failed to update document status after processing error",
                extra={"doc_id": document_id},
                exc_info=db_exc,
            )
        return {"status": "failed", "error": str(exc)}

    finally:
        # For S3: local_path is a temp download — always clean it up regardless of outcome
        if local_path and local_path != storage_ref and os.path.exists(local_path):
            os.remove(local_path)
            logger.debug("Temp file cleaned up", extra={"doc_id": document_id, "path": local_path})
        db.close()

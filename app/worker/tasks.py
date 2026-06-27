"""
Celery tasks for asynchronous PDF ingestion.

``process_pdf_task`` is the only task. It reads a PDF from storage,
splits the text into overlapping chunks, embeds each chunk with
``all-MiniLM-L6-v2``, and persists the vectors to PostgreSQL via pgvector.
"""

import os

import pdfplumber
import pypdfium2 as pdfium
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader
from rapidocr_onnxruntime import RapidOCR
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings
from app.core.logger import get_logger, request_id_ctx
from app.db.models import ChunkType, Document, DocumentChunk, ProcessingStatus
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
_ocr_engine: RapidOCR | None = None


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


def _get_ocr_engine() -> RapidOCR:
    """Return the process-level OCR engine, loading it on first call."""
    global _ocr_engine
    if _ocr_engine is None:
        logger.info("Loading OCR engine", extra={"engine": "rapidocr-onnxruntime"})
        _ocr_engine = RapidOCR()
        logger.info("OCR engine loaded")
    return _ocr_engine


def _embed_and_store_chunks(*, db, document_id: str, chunks: list[tuple[ChunkType, str]]) -> None:
    """Embed chunk text and stage DocumentChunk rows in the transaction."""
    embedding_model = _get_embedding_model()
    for i, chunk in enumerate(chunks):
        chunk_type, text_content = chunk
        vector = embedding_model.embed_query(text_content)
        db.add(
            DocumentChunk(
                document_id=document_id,
                chunk_type=chunk_type,
                text_content=text_content,
                embedding=vector,
            )
        )
        if (i + 1) % 10 == 0:
            logger.debug(
                "Embedding progress",
                extra={"doc_id": document_id, "embedded": i + 1, "total": len(chunks)},
            )


def _table_to_text(table: list[list[str | None]]) -> str:
    """Render extracted table rows into deterministic pipe-separated text."""
    rows: list[str] = []
    for row in table:
        cells = [(cell or "").strip().replace("\n", " ") for cell in row]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _extract_ocr_blocks(local_path: str, page_indexes: list[int]) -> list[str]:
    """Extract OCR text for selected page indexes using rendered page images."""
    if not page_indexes:
        return []

    ocr_engine = _get_ocr_engine()
    ocr_blocks: list[str] = []
    target_pages = set(page_indexes)

    pdf = pdfium.PdfDocument(local_path)
    try:
        for idx in range(len(pdf)):
            if idx not in target_pages:
                continue
            page = pdf[idx]
            bitmap = page.render(scale=2)
            image = bitmap.to_numpy()
            result, _ = ocr_engine(image)

            lines: list[str] = []
            for item in result or []:
                if len(item) < 3:
                    continue
                text = str(item[1]).strip()
                score = float(item[2])
                if text and score >= 0.5:
                    lines.append(text)

            if lines:
                ocr_blocks.append("\n".join(lines))
    finally:
        pdf.close()

    return ocr_blocks


def _extract_pdf_content(local_path: str) -> tuple[list[str], list[str], list[str], int]:
    """Extract free text blocks, table blocks, and OCR blocks from a PDF file."""
    text_blocks: list[str] = []
    table_blocks: list[str] = []
    pages_needing_ocr: list[int] = []

    with pdfplumber.open(local_path) as pdf:
        page_count = len(pdf.pages)
        for idx, page in enumerate(pdf.pages):
            page_text = (page.extract_text() or "").strip()
            if page_text:
                text_blocks.append(page_text)

            page_has_table = False
            for table in page.extract_tables() or []:
                table_text = _table_to_text(table)
                if table_text:
                    table_blocks.append(table_text)
                    page_has_table = True

            if not page_text and not page_has_table:
                pages_needing_ocr.append(idx)

    ocr_blocks = _extract_ocr_blocks(local_path, pages_needing_ocr)

    if not text_blocks and not table_blocks and not ocr_blocks:
        # Fallback: pypdf occasionally extracts text where pdfplumber returns nothing.
        reader = PdfReader(local_path)
        page_count = len(reader.pages)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if full_text:
            text_blocks.append(full_text)

    return text_blocks, table_blocks, ocr_blocks, page_count


def _split_blocks(blocks: list[str]) -> list[str]:
    """Split extracted blocks into embedding-sized chunks."""
    splitter = _get_text_splitter()
    chunks: list[str] = []
    for block in blocks:
        content = block.strip()
        if not content:
            continue
        chunks.extend(splitter.split_text(content))
    return chunks


def _set_failed_status(*, db, doc: Document, document_id: str) -> None:
    """Best-effort transition of a document to FAILED after processing errors."""
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


def _cleanup_temp_file(*, local_path: str | None, storage_ref: str, document_id: str) -> None:
    """Delete temporary local files created by storage adapters (e.g. S3 downloads)."""
    if local_path and local_path != storage_ref and os.path.exists(local_path):
        os.remove(local_path)
        logger.debug("Temp file cleaned up", extra={"doc_id": document_id, "path": local_path})


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

        text_blocks, table_blocks, ocr_blocks, page_count = _extract_pdf_content(local_path)
        text_char_count = sum(len(block) for block in text_blocks)
        table_char_count = sum(len(block) for block in table_blocks)
        ocr_char_count = sum(len(block) for block in ocr_blocks)
        logger.info(
            "PDF extraction complete",
            extra={
                "doc_id": document_id,
                "pages": page_count,
                "text_chars": text_char_count,
                "table_chars": table_char_count,
                "ocr_chars": ocr_char_count,
                "tables": len(table_blocks),
                "ocr_blocks": len(ocr_blocks),
            },
        )

        if text_char_count == 0 and table_char_count == 0 and ocr_char_count == 0:
            logger.warning(
                "PDF contains no extractable text/tables/OCR content",
                extra={"doc_id": document_id, "pages": page_count},
            )

        text_chunks = _split_blocks(text_blocks)
        table_chunks = _split_blocks(table_blocks)
        ocr_chunks = _split_blocks(ocr_blocks)
        chunks: list[tuple[ChunkType, str]] = (
            [(ChunkType.TEXT, item) for item in text_chunks]
            + [(ChunkType.TABLE, item) for item in table_chunks]
            + [(ChunkType.OCR, item) for item in ocr_chunks]
        )
        logger.info(
            "Text split into chunks",
            extra={
                "doc_id": document_id,
                "chunk_count": len(chunks),
                "text_chunks": len(text_chunks),
                "table_chunks": len(table_chunks),
                "ocr_chunks": len(ocr_chunks),
                "chunk_size": settings.CHUNK_SIZE,
            },
        )

        _embed_and_store_chunks(db=db, document_id=doc.id, chunks=chunks)

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
        _set_failed_status(db=db, doc=doc, document_id=document_id)
        return {"status": "failed", "error": str(exc)}

    finally:
        # For S3: local_path is a temp download — always clean it up regardless of outcome.
        _cleanup_temp_file(local_path=local_path, storage_ref=storage_ref, document_id=document_id)
        db.close()

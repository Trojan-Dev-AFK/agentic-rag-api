"""LangGraph tool: semantic search over document chunks using pgvector cosine distance."""

from contextvars import ContextVar, Token

from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logger import get_logger
from app.db.models import Document, DocumentChunk
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

# Lazy singleton — loaded on the first search_documents call, not at import time.
# Uvicorn --reload spawns a reloader process and a worker process; both import
# every module. Eager loading here would load the model twice (once per process)
# even though only the worker process ever runs queries.
_embeddings_model: HuggingFaceEmbeddings | None = None
_search_company_id: ContextVar[str | None] = ContextVar("search_company_id", default=None)
_search_query_counts: ContextVar[dict[str, int] | None] = ContextVar("search_query_counts", default=None)


def _get_embeddings_model() -> HuggingFaceEmbeddings:
    """Return the process-level embedding model, loading it on first call."""
    global _embeddings_model
    if _embeddings_model is None:
        logger.info("Loading embedding model for vector search", extra={"model": settings.EMBEDDING_MODEL})
        _embeddings_model = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
        logger.info("Embedding model ready")
    return _embeddings_model


def warmup_vector_search() -> bool:
    """Preload the embedding model and return True when this call performed the initial load."""
    was_cold = _embeddings_model is None
    _get_embeddings_model()
    return was_cold


def set_search_company_scope(company_id: str | None) -> Token:
    """Set the tenant scope for vector search in the current request/task context."""
    return _search_company_id.set(company_id)


def reset_search_company_scope(token: Token) -> None:
    """Reset the tenant scope for vector search in the current request/task context."""
    _search_company_id.reset(token)


def set_search_query_state() -> Token:
    """Initialise per-request duplicate-query counters for vector search."""
    return _search_query_counts.set({})


def reset_search_query_state(token: Token) -> None:
    """Reset per-request duplicate-query counters for vector search."""
    _search_query_counts.reset(token)


@tool
async def search_documents(query: str) -> str:
    """
    Search the database for relevant document chunks based on a semantic query.
    Use this tool whenever you need to find factual information from the user's uploaded documents.
    """
    company_id = _search_company_id.get()
    if not company_id:
        logger.error("Vector search blocked — missing company scope")
        return "Search context is unavailable for this request."

    logger.info(
        "Vector search invoked",
        extra={"query_preview": query[:120], "company_id": company_id},
    )

    normalized_query = " ".join(query.lower().split())
    query_counts = _search_query_counts.get()
    if query_counts is None:
        query_counts = {}
        _search_query_counts.set(query_counts)

    repeat_count = query_counts.get(normalized_query, 0)
    if repeat_count >= 1:
        logger.warning(
            "Vector search blocked — duplicate query loop detected",
            extra={"query_preview": query[:120], "company_id": company_id, "repeat_count": repeat_count},
        )
        return (
            "You already ran this same search multiple times. "
            "Do not call search_documents again for this query; provide your best final answer now."
        )
    query_counts[normalized_query] = repeat_count + 1

    try:
        query_vector = _get_embeddings_model().embed_query(query)
    except Exception as exc:
        logger.error("Embedding generation failed", exc_info=exc)
        return "Search is temporarily unavailable. Please try again."

    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DocumentChunk.text_content)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(Document.company_id == company_id)
                .order_by(DocumentChunk.embedding.cosine_distance(query_vector))
                .limit(5)
            )
            result = await db.execute(stmt)
            chunks = result.scalars().all()
    except SQLAlchemyError as exc:
        logger.error("Vector search database query failed", exc_info=exc)
        return "Search is temporarily unavailable due to a database error."

    if not chunks:
        logger.info("Vector search returned no results", extra={"query_preview": query[:120]})
        return "No relevant information found in the documents."

    logger.info("Vector search completed", extra={"results": len(chunks), "company_id": company_id})
    return "\n\n---\n\n".join(chunks)

"""LangGraph tool: semantic search over document chunks using pgvector cosine distance."""

from langchain_core.tools import tool
from langchain_huggingface import HuggingFaceEmbeddings
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import settings
from app.core.logger import get_logger
from app.db.models import DocumentChunk
from app.db.session import AsyncSessionLocal

logger = get_logger(__name__)

logger.info("Loading embedding model for vector search", extra={"model": settings.EMBEDDING_MODEL})
embeddings_model = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)
logger.info("Embedding model ready")


@tool
async def search_documents(query: str) -> str:
    """
    Search the database for relevant document chunks based on a semantic query.
    Use this tool whenever you need to find factual information from the user's uploaded documents.
    """
    logger.info("Vector search invoked", extra={"query_preview": query[:120]})

    try:
        query_vector = embeddings_model.embed_query(query)
    except Exception as exc:
        logger.error("Embedding generation failed", exc_info=exc)
        return "Search is temporarily unavailable. Please try again."

    try:
        async with AsyncSessionLocal() as db:
            stmt = (
                select(DocumentChunk.text_content)
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

    logger.info("Vector search completed", extra={"results": len(chunks)})
    return "\n\n---\n\n".join(chunks)

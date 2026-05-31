from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.tools import tool
from sqlalchemy import select

from app.core.config import settings
from app.db.models import DocumentChunk
from app.db.session import AsyncSessionLocal

# We load the exact same model used in our ingestion pipeline.
# Initializing it here ensures it loads into memory once when the app starts.
embeddings_model = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)

@tool
# This LangChain decorator automatically inspects the function signature and the docstring.
# When we pass this to an LLM, the LLM reads the docstring to mathematically calculate when and how to use the function.
async def search_documents(query: str) -> str:
    """
    Search the database for relevant document chunks based on a semantic query.
    Use this tool whenever you need to find factual information from the user's uploaded documents.
    """
    # 1. Convert the agent's text query into a 384-dimension vector
    query_vector = embeddings_model.embed_query(query)

    async with AsyncSessionLocal() as db:
        # 2. Build the SQLAlchemy query (Global Search Only)
        stmt = select(DocumentChunk.text_content).order_by(
            DocumentChunk.embedding.cosine_distance(query_vector)
        ).limit(5)

        # 3. Execute the query asynchronously
        result = await db.execute(stmt)
        chunks = result.scalars().all()

    # 4. Format the output for the LLM
    if not chunks:
        return "No relevant information found in the documents."

    return "\n\n---\n\n".join(chunks)
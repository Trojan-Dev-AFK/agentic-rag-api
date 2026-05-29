import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base
from app.db.session import engine

# Import your cleanly separated routers
from app.api.v1.endpoints import chat, documents

# Ensure uploads directory exists on boot
os.makedirs("uploads", exist_ok=True)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        from sqlalchemy import text
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(
    title="Agentic RAG API",
    description="Enterprise API for Document Analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# Wire up the routers
app.include_router(chat.router, prefix="/v1/chat", tags=["Agent"])
app.include_router(documents.router, prefix="/v1/documents", tags=["Documents"])

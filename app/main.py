import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text

from app.api.v1.endpoints import auth, chat, companies, documents, users
from app.db.session import engine

os.makedirs("uploads", exist_ok=True)

_REQUIRED_TABLES = {"companies", "users", "token_sessions", "documents", "document_chunks"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = ANY(:tables)"
            ),
            {"tables": list(_REQUIRED_TABLES)},
        )
        existing = {row[0] for row in result}
        missing = _REQUIRED_TABLES - existing
        if missing:
            raise RuntimeError(
                f"Missing database tables: {sorted(missing)}. "
                "Run 'alembic upgrade head' before starting the application."
            )
    yield
    await engine.dispose()

app = FastAPI(
    title="Agentic RAG API",
    description="Enterprise API for Document Analysis",
    version="1.0.0",
    lifespan=lifespan,
)

# Wire up the routers
app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/v1/chat", tags=["Agent"])
app.include_router(documents.router, prefix="/v1/documents", tags=["Documents"])
app.include_router(companies.router, prefix="/v1/companies", tags=["Companies"])
app.include_router(users.router, prefix="/v1/users", tags=["Users"])

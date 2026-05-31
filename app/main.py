"""
FastAPI application entry point.

Wires together routers, middleware, exception handlers, and the lifespan startup
check that verifies all required database tables exist before accepting traffic.
"""

import os
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1.endpoints import auth, chat, companies, documents, users
from app.core.config import settings
from app.core.exceptions import (
    AppException,
    app_exception_handler,
    http_exception_handler,
    unhandled_exception_handler,
)
from app.core.logger import get_logger, request_id_ctx, setup_logging
from app.db.session import engine

# Initialise structured logging before anything else touches the logging system
setup_logging()
logger = get_logger(__name__)

if settings.DOCUMENT_STORAGE == "LOCAL":
    os.makedirs(settings.LOCAL_UPLOAD_DIR, exist_ok=True)

_REQUIRED_TABLES = {"companies", "users", "token_sessions", "documents", "document_chunks"}


class _RequestIDMiddleware(BaseHTTPMiddleware):
    """Attaches a correlation ID to every request and echoes it in the response header."""

    async def dispatch(self, request, call_next):
        """Inject a request ID into the logging context and echo it in the response."""
        req_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        token = request_id_ctx.set(req_id)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = req_id
            return response
        finally:
            request_id_ctx.reset(token)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Verify the database schema on startup and dispose the engine on shutdown."""
    logger.info("Application starting up", extra={"storage_backend": settings.DOCUMENT_STORAGE})
    try:
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
                logger.critical(
                    "Required database tables are missing — refusing to start",
                    extra={"missing_tables": sorted(missing)},
                )
                raise RuntimeError(
                    f"Missing database tables: {sorted(missing)}. "
                    "Run 'alembic upgrade head' before starting the application."
                )
        logger.info("Database schema verified", extra={"tables": sorted(_REQUIRED_TABLES)})
    except RuntimeError:
        raise
    except Exception as exc:
        logger.critical("Database connectivity check failed", exc_info=exc)
        raise

    yield

    logger.info("Application shutting down")
    await engine.dispose()


_TAGS_METADATA = [
    {
        "name": "Auth",
        "description": (
            "Obtain and revoke JWT bearer tokens. Every other endpoint requires "
            "`Authorization: Bearer <token>` in the request header."
        ),
    },
    {
        "name": "Companies",
        "description": (
            "Platform-level tenant management. "
            "**Restricted to `super_admin` accounts.** "
            "A company groups users and documents together in an isolated namespace."
        ),
    },
    {
        "name": "Users",
        "description": (
            "Manage users inside a company. "
            "**Restricted to company `admin` accounts.** "
            "Admins can only see and modify users within their own company — "
            "any cross-company attempt returns **403**."
        ),
    },
    {
        "name": "Documents",
        "description": (
            "Upload PDFs for RAG ingestion and track processing status. "
            "**Restricted to company `admin` accounts.** "
            "After upload the file is stored (local or S3) and processed asynchronously by a Celery worker "
            "which splits the text into chunks, embeds each chunk with `all-MiniLM-L6-v2`, "
            "and stores the vectors in PostgreSQL via pgvector."
        ),
    },
    {
        "name": "Agent",
        "description": (
            "Conversational RAG interface powered by LangGraph + Ollama (`llama3.1`). "
            "Available to **`admin` and `employee`** accounts. `super_admin` is blocked. "
            "The agent can call two tools: `search_documents` (pgvector cosine search) "
            "and `generate_graph` (Plotly chart builder)."
        ),
    },
]

app = FastAPI(
    title="Agentic RAG API",
    description=(
        "A multi-tenant REST API for uploading PDFs and querying them through a conversational AI agent.\n\n"
        "## Roles\n"
        "| Role | Company | Capabilities |\n"
        "|------|---------|-------------|\n"
        "| `super_admin` | none | Create and manage companies |\n"
        "| `admin` | required | Manage users and documents within their company; use chat |\n"
        "| `employee` | required | Use chat only |\n\n"
        "## Authentication\n"
        "Call `POST /v1/auth/login` with `username` and `password` (form data) to receive a JWT. "
        "Pass it as `Authorization: Bearer <token>` on all subsequent requests.\n\n"
        "All timestamps in responses are formatted as `DD:MM:YYYY HH:MM:SS.mmm` (UTC)."
    ),
    version="1.0.0",
    lifespan=lifespan,
    openapi_tags=_TAGS_METADATA,
)

app.add_middleware(_RequestIDMiddleware)
app.add_exception_handler(AppException, app_exception_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/v1/chat", tags=["Agent"])
app.include_router(documents.router, prefix="/v1/documents", tags=["Documents"])
app.include_router(companies.router, prefix="/v1/companies", tags=["Companies"])
app.include_router(users.router, prefix="/v1/users", tags=["Users"])

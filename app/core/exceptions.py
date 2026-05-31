"""
Application exception hierarchy and FastAPI global exception handlers.

All handlers return a JSON body ``{"detail": "..."}`` so the API never returns
an HTML error page or an unhandled Python traceback to the client.
"""

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.logger import get_logger

_log = get_logger("app.exceptions")


class AppException(Exception):
    """Base class for all application-level exceptions that map to HTTP responses."""

    status_code: int = 500
    detail: str = "Internal server error"

    def __init__(self, detail: str | None = None) -> None:
        self.detail = detail or self.__class__.detail
        super().__init__(self.detail)


class StorageError(AppException):
    """Raised when a file storage operation (local or S3) fails unexpectedly."""

    status_code = 500
    detail = "Storage operation failed"


class AgentError(AppException):
    """Raised when the LangGraph agent fails to produce a response."""

    status_code = 502
    detail = "Agent service unavailable"


# ---------------------------------------------------------------------------
# Global exception handlers — registered in main.py
# ---------------------------------------------------------------------------


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    """Log and return a JSON response for any ``AppException`` subclass."""
    _log.error(
        "Application error",
        extra={
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url),
            "method": request.method,
        },
    )
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Log and return a JSON response for FastAPI ``HTTPException`` instances."""
    level = _log.warning if exc.status_code < 500 else _log.error
    level(
        "HTTP exception",
        extra={
            "status_code": exc.status_code,
            "detail": exc.detail,
            "path": str(request.url),
            "method": request.method,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None) or {},
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Last-resort handler: log CRITICAL and return a safe 500 for any unhandled exception."""
    # Safety net — HTTPException has its own handler above but may still reach here
    if isinstance(exc, HTTPException):
        return await http_exception_handler(request, exc)
    _log.critical(
        "Unhandled exception",
        extra={"path": str(request.url), "method": request.method},
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

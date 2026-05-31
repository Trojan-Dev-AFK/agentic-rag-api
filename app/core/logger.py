"""
Structured JSON logging with per-request correlation IDs.

Usage::

    from app.core.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Something happened", extra={"user_id": uid, "doc_id": did})

Call ``setup_logging()`` once at application startup (done in ``main.py``).
Set ``LOG_LEVEL=DEBUG`` in the environment to enable verbose output.
"""

import contextvars
import json
import logging
import os
import sys
from datetime import UTC, datetime

# Propagated through every async context — set once per request by middleware,
# set to "task:<celery_id>" for Celery workers.
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

# Standard LogRecord attributes that we never want to re-emit as extra fields.
_SKIP_ATTRS = frozenset(
    {
        "args",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class _JSONFormatter(logging.Formatter):
    """Emit each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        """Serialise ``record`` to a JSON string with standard and extra fields."""
        record.message = record.getMessage()
        entry: dict = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": request_id_ctx.get(),
            "msg": record.message,
        }
        for k, v in record.__dict__.items():
            if k not in _SKIP_ATTRS:
                entry[k] = v
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


def setup_logging() -> None:
    """Configure root logger. Call once at application startup."""
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JSONFormatter())
    root.addHandler(handler)

    # Silence noisy third-party loggers that add no debugging value
    for noisy in (
        "uvicorn.access",
        "sqlalchemy.engine",
        "httpx",
        "sentence_transformers",
        "transformers",
        "torch",
    ):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a named logger. Pass ``__name__`` for automatic module scoping."""
    return logging.getLogger(name)

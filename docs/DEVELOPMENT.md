# Development Guide

Setup, conventions, and workflows for contributors.

---

## Local setup

```bash
git clone <repo>
cd agentic-rag-api
uv sync --group dev   # installs runtime + dev tools (ruff, black, interrogate)
cp .env.example .env  # fill in local values
docker-compose up -d  # start PostgreSQL + Redis
alembic upgrade head  # apply migrations
uvicorn app.main:app --reload
```

The API is available at `http://localhost:8000`. Interactive docs at `http://localhost:8000/docs`.

---

## Project layout

```
app/
├── main.py              # app factory, middleware, exception handlers, lifespan
├── api/
│   ├── dependencies.py  # JWT decode + role guards
│   └── v1/endpoints/    # thin transport handlers only (request parsing + response mapping)
├── services/            # business logic layer used by endpoints
│   ├── auth_service.py
│   ├── companies_service.py
│   ├── users_service.py
│   ├── documents_service.py
│   └── chat_service.py
├── agent/
│   ├── graph.py         # LangGraph StateGraph (compiled once at startup)
│   └── tools/           # search_documents
├── core/
│   ├── config.py        # all settings (Pydantic BaseSettings)
│   ├── logger.py        # JSON structured logging
│   ├── exceptions.py    # AppException hierarchy + global handlers
│   └── security.py      # JWT + bcrypt utilities
├── db/
│   ├── session.py       # async engine, session factory
│   └── models/          # SQLAlchemy ORM models (one file per model)
├── schemas/             # Pydantic request/response models
├── storage/             # pluggable file storage (local + S3)
└── worker/
    ├── celery_app.py    # Celery instance
    └── tasks.py         # process_pdf_task
```

---

## Code standards

### Formatting and linting

All quality gates run in CI. Run them locally before pushing:

```bash
uv run ruff check .                             # lint (pycodestyle, pyflakes, isort, pyupgrade, bugbear)
uv run ruff check . --fix                       # auto-fix all fixable violations
uv run black --check .                          # verify formatting
uv run python scripts/lint_thin_endpoints.py   # enforce thin endpoint imports
uv run interrogate app/                         # docstring coverage (minimum 80%)
uv run vulture app scripts --min-confidence 70 # dead-code scan (production code only)
```

Configuration lives in `pyproject.toml` under `[tool.ruff]`, `[tool.black]`,
`[tool.interrogate]`, and `[tool.vulture]`.

### Separation of concerns

- Endpoint modules in `app/api/v1/endpoints/` must stay thin and avoid business logic.
- Put domain/business logic in `app/services/` modules.
- Endpoints should delegate to services and only handle HTTP-level concerns
    (routing, dependency injection, status codes, response models).

### Line length

**120 characters** maximum — enforced by black and checked by ruff.
This applies to code, docstrings, and inline comments.

### Docstring style

Google style with text starting on a new line after `"""`:

```python
def my_function(arg1: str, arg2: int) -> bool:
    """
    Short one-line summary.

    Extended description if needed. Keep lines under 120 chars.

    Args:
        arg1: Description of arg1.
        arg2: Description of arg2.

    Returns:
        True if successful, False otherwise.

    Raises:
        ValueError: If arg1 is empty.
    """
```

Single-line docstrings stay on one line:

```python
def simple() -> str:
    """Return the configured value."""
```

### Import ordering

Managed by ruff (`I` rules). Groups in order:
1. Standard library
2. Third-party packages
3. First-party (`app.*`)

Run `ruff check app/ --fix` to auto-sort.

### Type hints

- Use `X | Y` union syntax (Python 3.10+), not `Optional[X]` or `Union[X, Y]`.
- Use `list[X]` and `dict[K, V]` (lowercase), not `List[X]` or `Dict[K, V]`.
- Use `(str, enum.Enum)` for SQLAlchemy string enums in this project.

---

## Singleton pattern

Expensive objects must be initialised **once per process**:

```python
# CORRECT — module-level singleton
embeddings_model = HuggingFaceEmbeddings(model_name=settings.EMBEDDING_MODEL)

# CORRECT — lazy singleton (use when the module is imported by a process
# that never actually calls the function, to avoid wasted memory)
_model: SomeModel | None = None

def _get_model() -> SomeModel:
    global _model
    if _model is None:
        _model = SomeModel(...)
    return _model

# WRONG — instantiates on every request/task
@router.post("/endpoint")
async def handler():
    model = SomeModel(...)  # re-creates every request!
```

See [ARCHITECTURE.md](ARCHITECTURE.md) for the full singleton table.

---

## Adding a new endpoint

1. Create or update the router file in `app/api/v1/endpoints/`.
2. Use the appropriate dependency: `require_admin`, `require_super_admin`, or
   `require_company_user`.
3. Add a Pydantic request schema in `app/schemas/` if needed.
4. Register the router in `app/main.py`.
5. Add a row to the API endpoints table in [README.md](../README.md).
6. Add logging at appropriate levels (see existing endpoints for patterns).

---

## Adding a new storage backend

1. Create `app/storage/your_backend.py` implementing `StorageBackend` from `app/storage/base.py`.
2. Add the new option to `DOCUMENT_STORAGE` in `app/core/config.py` (extend the `Literal`).
3. Update the `get_storage()` factory in `app/storage/__init__.py`.
4. Add validation in `Settings._validate_cloud_storage` if credentials are required.

---

## Database migrations

Alembic manages the schema. Always create a new migration after changing a model:

```bash
# After editing an ORM model
alembic revision --autogenerate -m "short description"
alembic upgrade head
```

Review the generated migration file before committing — autogenerate sometimes misses
rename operations or vector column changes.

```bash
alembic downgrade -1   # roll back one step
alembic current        # show active revision
```

---

## Testing

```bash
uv run pytest -q
```

Tests live in `tests/` and currently include:
- Unit tests for `app/services/*` with mocked async session behavior.
- Endpoint integration tests for role/scoping behavior using FastAPI dependency overrides.

These tests do not require a dedicated test database.

---

## Logging in new code

Always use the module-level logger:

```python
from app.core.logger import get_logger

logger = get_logger(__name__)

logger.info("Operation succeeded", extra={"doc_id": doc.id, "company_id": company_id})
logger.warning("Access denied", extra={"user_id": user.id, "reason": "wrong company"})
logger.error("Unexpected failure", exc_info=exc)
```

- Use `INFO` for normal operations.
- Use `WARNING` for expected failures (bad credentials, 403, 404).
- Use `ERROR` for unexpected failures that degrade functionality.
- Use `CRITICAL` for startup failures or total service loss.
- Never log passwords, tokens, or PII.
- Always include relevant IDs (`user_id`, `doc_id`, `company_id`) as `extra` fields so logs
  are filterable.

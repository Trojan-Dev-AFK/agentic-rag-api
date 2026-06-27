# Agentic RAG API

A multi-tenant REST API that lets companies upload PDF documents and interrogate them
through a conversational AI agent. Each company's data is fully isolated.

---

## Roles

| Role | `company_id` | Capabilities |
|------|-------------|--------------|
| `super_admin` | `null` | Create and manage companies. No access to company data or chat. |
| `admin` | required | Manage users and documents within their own company. Use chat. |
| `employee` | required | Use chat only. |

Cross-company access on users and documents always returns **403** — never a silent filter.

---

## Quick start

```bash
uv sync --group dev       # install all dependencies
cp .env.example .env      # configure environment
docker-compose up -d      # start PostgreSQL + Redis
alembic upgrade head      # apply migrations
uvicorn app.main:app --reload
```

Interactive API docs: `http://localhost:8000/docs`

Full setup guide: [docs/RUNBOOK.md](docs/RUNBOOK.md)

---

## API endpoints

| Method | Path | Access |
|--------|------|--------|
| `POST` | `/v1/auth/login` | Public |
| `POST` | `/v1/auth/logout` | Authenticated |
| `GET` | `/v1/auth/me` | Authenticated |
| `GET` | `/v1/auth/me/sessions` | Authenticated |
| `GET` | `/v1/auth/sessions/company` | Admin (own company) or Super Admin |
| `POST` | `/v1/companies/` | Super Admin |
| `GET` | `/v1/companies/` | Super Admin |
| `GET` | `/v1/companies/{id}` | Super Admin |
| `PUT` | `/v1/companies/{id}` | Super Admin |
| `DELETE` | `/v1/companies/{id}` | Super Admin |
| `POST` | `/v1/users/` | Admin (own company) or Super Admin |
| `GET` | `/v1/users/` | Admin (own company) or Super Admin |
| `GET` | `/v1/users/{id}` | Admin (own company) or Super Admin |
| `PUT` | `/v1/users/{id}` | Admin (own company) or Super Admin |
| `DELETE` | `/v1/users/{id}` | Admin (own company) or Super Admin |
| `POST` | `/v1/documents/upload` | Admin (own company) or Super Admin (with company_id) |
| `GET` | `/v1/documents/` | Admin (own company) or Super Admin |
| `GET` | `/v1/documents/{id}` | Admin (own company) or Super Admin |
| `DELETE` | `/v1/documents/{id}` | Admin (own company) or Super Admin |
| `POST` | `/v1/chat/invoke` | Admin or Employee |

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| Web framework | FastAPI |
| ASGI server | Uvicorn |
| ORM | SQLAlchemy 2 (async) |
| Migrations | Alembic |
| Database | PostgreSQL 16 + pgvector |
| Vector search | pgvector cosine distance |
| Embeddings | `sentence-transformers` (`all-MiniLM-L6-v2`, 384-dim) |
| LLM | Ollama (`llama3.1`) via `langchain-ollama` |
| Agent framework | LangGraph |
| Task queue | Celery + Redis |
| Auth | JWT (`python-jose`) + bcrypt |
| Cloud storage | `boto3` (AWS S3) |
| Config | Pydantic Settings |
| Dependency management | uv |

---

## Environment variables

Create a `.env` file in the project root:

```env
# Database
DATABASE_URL_ASYNC=postgresql+asyncpg://agenticraguser:agenticragpwd@localhost:5432/rag_db
DATABASE_URL_SYNC=postgresql://agenticraguser:agenticragpwd@localhost:5432/rag_db

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=your-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Embedding
EMBEDDING_MODEL=all-MiniLM-L6-v2
CHUNK_SIZE=1000
CHUNK_OVERLAP=200

# Encoding
ENCODING=utf-8

# Logging (optional — defaults to INFO)
# LOG_LEVEL=DEBUG   # DEBUG also enables SQLAlchemy query logging

# Document storage: LOCAL or CLOUD_STORAGE
DOCUMENT_STORAGE=LOCAL
LOCAL_UPLOAD_DIR=uploads

# AWS S3 (only required when DOCUMENT_STORAGE=CLOUD_STORAGE)
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# AWS_REGION=ap-south-1
# S3_BUCKET_NAME=agentic-rag-api
```

Full variable reference: [docs/RUNBOOK.md#environment-variables-reference](docs/RUNBOOK.md#environment-variables-reference)

---

## Documentation

| Document | Contents |
|----------|----------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Component diagram, request lifecycle, singleton model loading, storage backend design, RBAC model |
| [docs/RUNBOOK.md](docs/RUNBOOK.md) | Full setup, service startup/shutdown, migrations, monitoring, common ops tasks, S3 setup, backup/restore |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Code standards, docstring style, singleton pattern, adding endpoints, migrations, logging conventions |

---

## Development commands

```bash
# Linting and formatting
uv run ruff check .                             # lint + complexity + commented-out code checks
uv run ruff check . --fix                       # auto-fix
uv run black --check .                          # format verification
uv run python scripts/lint_thin_endpoints.py   # endpoint thinness rule
uv run interrogate app/                         # docstring coverage (min 80%)
uv run vulture app scripts --min-confidence 70 # dead-code scan

# Dependencies
uv add <package>       # add a runtime dependency
uv add --group dev <p> # add a dev-only dependency
uv sync                # sync venv to lockfile
uv sync --group dev    # include dev tools

# Database
alembic upgrade head                          # apply all migrations
alembic revision --autogenerate -m "desc"     # generate a migration
alembic downgrade -1                          # roll back one step

# Celery worker (separate terminal)
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES  # macOS only
celery -A app.worker.celery_app worker --pool=solo --loglevel=info

# Tests
uv run pytest -q
```

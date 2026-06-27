# Runbook

Operational guide for deploying, running, monitoring, and troubleshooting the Agentic RAG API.

---

## Prerequisites

| Requirement | Version | Notes |
|-------------|---------|-------|
| Python | 3.13+ | Managed via `uv` |
| PostgreSQL | 16+ | Must have the `vector` extension |
| Redis | 7+ | Celery broker and result backend |
| Ollama | latest | Must have `llama3.1` pulled |
| Docker | any | Optional — used for local infra via docker-compose |
| uv | 0.11+ | Dependency and venv manager |

---

## First-time setup

### 1. Clone and install

```bash
git clone <repo>
cd agentic-rag-api
uv sync              # installs all runtime deps into .venv
uv sync --group dev  # also installs ruff, black, interrogate, pytest, vulture
```

### 2. Configure environment

Copy the template and fill in real values:

```bash
cp .env.example .env   # or create .env manually
```

Minimum required values:

```env
DATABASE_URL_ASYNC=postgresql+asyncpg://user:pass@localhost:5432/rag_db
DATABASE_URL_SYNC=postgresql://user:pass@localhost:5432/rag_db
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<long-random-string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
LOGIN_RATE_LIMIT_ATTEMPTS=10
LOGIN_RATE_LIMIT_WINDOW_SECONDS=60
CHAT_RATE_LIMIT_REQUESTS=30
CHAT_RATE_LIMIT_WINDOW_SECONDS=60
CHAT_IDEMPOTENCY_TTL_SECONDS=300
TOKEN_SESSION_CACHE_TTL_SECONDS=60
VECTOR_SEARCH_CACHE_TTL_SECONDS=300
CHAT_HISTORY_CACHE_TTL_SECONDS=60
DOCUMENT_METADATA_CACHE_TTL_SECONDS=60
READINESS_REQUIRE_REDIS=true
DEFAULT_LIST_LIMIT=50
MAX_LIST_LIMIT=200
MAX_UPLOAD_BYTES=26214400
EMBEDDING_MODEL=all-MiniLM-L6-v2
CHUNK_SIZE=1000
CHUNK_OVERLAP=200
ENCODING=utf-8
DOCUMENT_STORAGE=LOCAL
LOCAL_UPLOAD_DIR=uploads
```

See [README.md](../README.md) for all available variables.

### 3. Start infrastructure

```bash
docker-compose up -d
docker compose ps
```

Starts API, Celery worker, PostgreSQL 16 with pgvector, and Redis.
Services use healthchecks; wait for `healthy` status before traffic.

Compose image tags are pinned directly in `docker-compose.yml`.

### 4. Run migrations

```bash
alembic upgrade head
```

Required for non-container/local process startup.
In Docker Compose mode, API startup runs migrations automatically before serving requests.

### 5. Pull the LLM

```bash
ollama pull llama3.1
```

The embedding model (`all-MiniLM-L6-v2`) is downloaded automatically by HuggingFace on
first use.

---

## Starting services

### API container

```bash
docker build -t agentic-rag-api:latest .
docker run --rm -p 8000:8000 --env-file .env agentic-rag-api:latest
```

Use this path for containerized deployments. PostgreSQL and Redis must be reachable from configured URLs.

### API server

When using Docker Compose, API and Celery worker both start automatically with `docker-compose up -d`.

For non-container/local process startup, run:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Remove `--reload` in production. Interactive docs are at `http://localhost:8000/docs`.

The API automatically performs a best-effort embedding warmup during startup to reduce
first-chat cold-start latency.

### Celery worker

Open a separate terminal. On macOS (Apple Silicon) first run:

```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

Then:

```bash
celery -A app.worker.celery_app worker --pool=solo --loglevel=info
```

Use `--pool=prefork` on Linux in production for true parallelism.

---

## Stopping services

```bash
# Stop docker infra
docker-compose down

# The API and Celery worker are stopped with Ctrl-C in their respective terminals.
# To stop Celery gracefully:
celery -A app.worker.celery_app control shutdown
```

---

## Environment variables reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL_ASYNC` | yes | — | asyncpg URL for FastAPI |
| `DATABASE_URL_SYNC` | yes | — | psycopg2 URL for Celery |
| `DB_POOL_SIZE` | no | `10` | API DB connection pool size |
| `DB_MAX_OVERFLOW` | no | `20` | API DB max overflow connections |
| `REDIS_URL` | yes | — | Redis connection string |
| `SECRET_KEY` | yes | — | JWT signing key (rotate periodically) |
| `ALGORITHM` | yes | — | JWT algorithm (use `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | yes | — | Token TTL in minutes |
| `LOGIN_RATE_LIMIT_ATTEMPTS` | no | `10` | Max login attempts per IP+username window |
| `LOGIN_RATE_LIMIT_WINDOW_SECONDS` | no | `60` | Login rate-limit window in seconds |
| `CHAT_RATE_LIMIT_REQUESTS` | no | `30` | Max chat invoke requests per user window |
| `CHAT_RATE_LIMIT_WINDOW_SECONDS` | no | `60` | Chat rate-limit window in seconds |
| `CHAT_IDEMPOTENCY_TTL_SECONDS` | no | `300` | Redis TTL for chat idempotency cache |
| `TOKEN_SESSION_CACHE_TTL_SECONDS` | no | `60` | Redis TTL for token-session validation cache |
| `VECTOR_SEARCH_CACHE_TTL_SECONDS` | no | `300` | Redis TTL for vector-search result cache |
| `CHAT_HISTORY_CACHE_TTL_SECONDS` | no | `60` | Redis TTL for chat conversation/message read cache |
| `DOCUMENT_METADATA_CACHE_TTL_SECONDS` | no | `60` | Redis TTL for document list/get metadata cache |
| `READINESS_REQUIRE_REDIS` | no | `true` | Require Redis connectivity for `/readyz` |
| `DEFAULT_LIST_LIMIT` | no | `50` | Default pagination limit for list/history endpoints |
| `MAX_LIST_LIMIT` | no | `200` | Maximum accepted pagination limit |
| `MAX_UPLOAD_BYTES` | no | `26214400` | Maximum PDF upload size in bytes (returns `413` when exceeded) |
| `EMBEDDING_MODEL` | yes | — | HuggingFace model name |
| `CHUNK_SIZE` | yes | — | Max chars per text chunk |
| `CHUNK_OVERLAP` | yes | — | Overlap chars between adjacent chunks |
| `ENCODING` | yes | — | Text encoding (use `utf-8`) |
| `DOCUMENT_STORAGE` | no | `LOCAL` | `LOCAL` or `CLOUD_STORAGE` |
| `LOCAL_UPLOAD_DIR` | no | `uploads` | Root dir for local file storage |
| `AWS_ACCESS_KEY_ID` | if S3 | — | AWS access key |
| `AWS_SECRET_ACCESS_KEY` | if S3 | — | AWS secret key |
| `AWS_REGION` | no | `ap-south-1` | S3 bucket region |
| `S3_BUCKET_NAME` | no | `agentic-rag-api` | S3 bucket name |
| `LOG_LEVEL` | no | `INFO` | Python log level; `DEBUG` enables SQL logging |

---

## Database migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Generate a new migration after changing a model
alembic revision --autogenerate -m "description of change"

# Roll back one step
alembic downgrade -1

# Show current revision
alembic current

# Show migration history
alembic history --verbose
```

---

## Monitoring and observability

### Log format

Every log line is a single JSON object:

```json
{
  "ts": "2026-05-31T14:30:45.123+00:00",
  "level": "INFO",
  "logger": "app.api.v1.endpoints.documents",
  "request_id": "a1b2c3d4-...",
  "msg": "Document upload received",
  "file_name": "report.pdf",
  "company_id": "c-...",
  "actor": "u-..."
}
```

**Useful fields to filter on:**

| Field | Purpose |
|-------|---------|
| `request_id` | Trace all logs for a single HTTP request across API and worker |
| `level` | Filter by severity (`WARNING`, `ERROR`, `CRITICAL`) |
| `logger` | Narrow to a specific module |
| `doc_id` | Trace a document through ingestion |
| `user_id` | Trace all activity by a user |

### Health indicators

| Symptom | Likely cause |
|---------|-------------|
| `CRITICAL` at startup | Missing DB tables — run `alembic upgrade head` |
| `CRITICAL` + `Missing database tables` | Same as above |
| `ERROR` + `PDF processing failed` | Corrupt PDF, disk full, or S3 auth issue |
| `ERROR` + `S3 upload failed` | Wrong AWS credentials or bucket policy |
| `ERROR` + `Vector search database query failed` | pgvector extension missing or DB unreachable |
| `WARNING` + `Vector search blocked — duplicate query loop detected` | Agent attempted repeated identical vector searches; guard forced finalisation |
| `WARNING` + `Attempt to use revoked token` | Normal post-logout token replay attempt |

### Agent warmup and loop guard

- The API performs a best-effort embedding warmup during startup.
- The chat graph uses a recursion limit of 8 to prevent long tool-call loops.
- The vector-search tool blocks repeated identical searches in a single request after one repeat.
- Chat conversations and messages are persisted in `chat_conversations` and `chat_messages`.
- Login and chat endpoints are Redis rate-limited (`429` when exceeded).
- Chat invoke supports `X-Idempotency-Key` to deduplicate retried requests for a bounded TTL.
- List/history endpoints support pagination via `limit` and `offset` query params.
- Document uploads larger than `MAX_UPLOAD_BYTES` are rejected with `413`.

### Health and readiness probes

- `GET /healthz`: process liveness probe, returns `200` when API process is running.
- `GET /readyz`: dependency readiness probe.
  - Verifies database connectivity.
  - Verifies Redis connectivity when `READINESS_REQUIRE_REDIS=true`.

### Log level

Set `LOG_LEVEL=DEBUG` in `.env` to enable:
- Embedding progress logs (every 10 chunks)
- SQLAlchemy query logs
- LangGraph agent node invocations

---

## Common operational tasks

### Create the first super_admin

```bash
uv run python scripts/create_superadmin.py --username superadmin --password <secure-password>
```

If running from the `scripts/` directory:

```bash
uv run python create_superadmin.py --username superadmin --password <secure-password>
```

### Rotate the SECRET_KEY

1. Update `SECRET_KEY` in `.env`.
2. Restart the API server.
3. All existing tokens are immediately invalidated (they fail HMAC verification).
4. Users must log in again.

### Re-ingest a failed document

Set the document status back to `PENDING` and re-queue:

```python
doc.status = ProcessingStatus.PENDING
session.commit()
from app.worker.tasks import process_pdf_task
process_pdf_task.delay(doc.id, storage_ref)
```

### Clear all token sessions for a user

```sql
DELETE FROM token_sessions WHERE user_id = '<uuid>';
```

### Purge all vector data for a company

```sql
-- Cascades automatically to document_chunks
DELETE FROM documents WHERE company_id = '<uuid>';
```

---

## S3 setup

1. Create a bucket named `agentic-rag-api` (or set `S3_BUCKET_NAME` to your bucket).
2. Create an IAM user with the following policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::agentic-rag-api/BACKEND/*"
    }
  ]
}
```

3. Set `DOCUMENT_STORAGE=CLOUD_STORAGE` and the AWS credentials in `.env`.
4. Files are stored at `BACKEND/{company_id}/{stem}_{DD-MM-YYYY_HH-MM-SS}.pdf`.

---

## Backup and restore

### Database

```bash
# Backup
pg_dump -U agenticraguser -d rag_db -F c -f backup.dump

# Restore
pg_restore -U agenticraguser -d rag_db -F c backup.dump
```

Vector embeddings are stored in the `document_chunks` table and are included in the dump.
There is no separate vector store to back up.

### Uploaded files (LOCAL mode only)

Back up the `uploads/` directory. In `CLOUD_STORAGE` mode, S3 manages durability.

---

## Dependency management

```bash
uv add <package>        # add a runtime dependency
uv add --group dev <p>  # add a dev-only dependency
uv remove <package>     # remove a dependency
uv sync                 # sync venv to uv.lock (runtime only)
uv sync --group dev     # sync venv including dev tools

# Security scans
uv run pip-audit --ignore-vuln CVE-2025-3000
uv run bandit -r app -q -x app/schemas
```

`CVE-2025-3000` is currently ignored because no upstream fixed torch release is available.

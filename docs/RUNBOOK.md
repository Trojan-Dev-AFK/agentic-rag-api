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
uv sync --group dev  # also installs ruff, black, interrogate
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
REDIS_URL=redis://localhost:6379/0
SECRET_KEY=<long-random-string>
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
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
```

Starts PostgreSQL 16 with pgvector and Redis.

### 4. Run migrations

```bash
alembic upgrade head
```

The API will refuse to start if this step is skipped.

### 5. Pull the LLM

```bash
ollama pull llama3.1
```

The embedding model (`all-MiniLM-L6-v2`) is downloaded automatically by HuggingFace on
first use.

---

## Starting services

### API server

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Remove `--reload` in production. Interactive docs are at `http://localhost:8000/docs`.

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
| `REDIS_URL` | yes | — | Redis connection string |
| `SECRET_KEY` | yes | — | JWT signing key (rotate periodically) |
| `ALGORITHM` | yes | — | JWT algorithm (use `HS256`) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | yes | — | Token TTL in minutes |
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
  "filename": "report.pdf",
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
| `WARNING` + `Attempt to use revoked token` | Normal post-logout token replay attempt |

### Log level

Set `LOG_LEVEL=DEBUG` in `.env` to enable:
- Embedding progress logs (every 10 chunks)
- SQLAlchemy query logs
- LangGraph agent node invocations

---

## Common operational tasks

### Create the first super_admin

There is no registration endpoint. Create the user directly:

```python
# Run in a Python shell with the venv activated:
from app.core.security import get_password_hash
from app.db.models import User, UserRole
# (use a sync SQLAlchemy session connected to DATABASE_URL_SYNC)
user = User(username="admin", hashed_password=get_password_hash("changeme"), role=UserRole.SUPER_ADMIN)
session.add(user); session.commit()
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
```

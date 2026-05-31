# Agentic RAG API

A multi-tenant REST API that lets companies upload PDF documents and interrogate them through a conversational AI agent. Each company's data is fully isolated. The platform operator manages companies; company admins manage their own users and documents; employees chat with the agent.

---

## Roles

| Role | `company_id` | Description |
|------|-------------|-------------|
| `super_admin` | `null` | Platform-level. Creates and manages companies. No access to company data or chat. |
| `admin` | required | Company-level. Manages users and documents within their own company only. |
| `employee` | required | Company-level. Chat access only. |

Cross-company access on users and documents always returns **403** — not a silent filter.

---

## System architecture

```
┌─────────────────────────────────────────────────┐
│                  FastAPI (HTTP)                  │
│  /v1/auth  /v1/companies  /v1/users              │
│  /v1/documents  /v1/chat                         │
└────────────┬───────────────────┬────────────────┘
             │                   │
   PDF upload │        chat query │
             ▼                   ▼
┌────────────────┐   ┌───────────────────────────┐
│  Celery Worker │   │     LangGraph Agent        │
│  (PDF ingestion│   │  ┌─────────┐  ┌─────────┐ │
│   chunking +   │   │  │  Agent  │→ │  Tools  │ │
│   embeddings)  │   │  │  (LLM)  │← │  node   │ │
└───────┬────────┘   └──────────────────┬────────┘
        │                               │
        ▼                               ▼
┌──────────────────────────────────────────────────┐
│          PostgreSQL 16 + pgvector                │
│  companies / users / token_sessions              │
│  documents / document_chunks (Vector 384)        │
└──────────────────────────────────────────────────┘
        ▲
        │ broker + backend
┌───────┴──────┐
│    Redis     │
└──────────────┘
```

---

## Data flows

### 1. Document ingestion

```
1. Admin  POST /v1/documents/upload  (multipart PDF)
          │
2.        FastAPI saves the PDF via the storage backend
          (LOCAL → uploads/{company_id}/, CLOUD_STORAGE → S3 BACKEND/{company_id}/),
          creates a Document row with status=PENDING,
          fires process_pdf_task.delay(doc_id, storage_ref) → Redis queue,
          returns 202 immediately
          │
3.        Celery worker picks up the task from Redis:
          ├─ sets status = PROCESSING
          ├─ reads PDF pages with pypdf.PdfReader
          ├─ splits full text into overlapping chunks
          │  (RecursiveCharacterTextSplitter, configurable size/overlap)
          ├─ for each chunk:
          │   · generates a 384-dim vector via HuggingFaceEmbeddings
          │     (all-MiniLM-L6-v2, same model used at query time)
          │   · inserts a DocumentChunk row (text + embedding)
          ├─ sets status = COMPLETED
          └─ deletes the PDF from storage (S3 or local disk)

4. Admin  GET /v1/documents/{id}  →  { status: "COMPLETED" }
```

### 2. Chat query

```
1. User   POST /v1/chat/invoke  { "query": "What was Q3 revenue?" }
          │
2.        FastAPI authenticates the JWT, blocks super_admin,
          passes the query to LangGraph app_graph.ainvoke()
          │
3.        LangGraph reasoning loop (Directed Cyclic Graph):
          │
          ├─ Agent node (Ollama llama3.1, temperature=0):
          │   reads the conversation history + system prompt,
          │   decides: answer directly OR call a tool
          │
          ├─ Tool node (if needed):
          │   · search_documents(query):
          │     - embeds the query with the same HuggingFace model
          │     - runs cosine distance search against document_chunks
          │     - returns top-5 matching text chunks
          │   · generate_graph(data_json):
          │     - builds a Plotly figure from structured JSON
          │     - returns the figure spec as a JSON payload
          │
          └─ loops back to Agent node to synthesise final answer
          │
4.        FastAPI returns:
          { "response": "...", "graph": <plotly payload or null> }
```

### 3. Authentication

```
POST /v1/auth/login
  · verifies username + bcrypt hash
  · mints a JWT containing { sub, role, company_id, jti }
    (jti = unique token ID, UUID)
  · persists a TokenSession row (jti, user_id, expires_at)
  · returns the token

Every protected endpoint:
  · FastAPI decodes the JWT (python-jose)
  · looks up the TokenSession by jti
  · rejects if: session missing / revoked_at set / logout_at set / expired

POST /v1/auth/logout
  · sets revoked_at + logout_at on the TokenSession row
  · that jti is now permanently invalid — no replay possible
```

---

## Database schema

```
companies          users               token_sessions
──────────         ──────              ──────────────
id (PK)            id (PK)             id (PK)
name (unique)      username (unique)   user_id → users.id
industry           hashed_password     jti (unique)
description        role (enum)         issued_at
created_at         company_id → co.id  expires_at
                   created_at          revoked_at
                                       logout_at
                                       ip_address
                                       user_agent

documents          document_chunks
─────────          ───────────────
id (PK)            id (PK)
filename           document_id → documents.id
status (enum)      text_content
company_id → co.id embedding  Vector(384)
created_at
```

**Cascade rules:**
- Delete company → deletes its users, documents, and chunks
- Delete user → deletes their token sessions
- Delete document → deletes its chunks (pgvector rows)

**Datetime format:** All timestamps are stored as `TIMESTAMPTZ` in PostgreSQL (UTC). API responses format them as `DD:MM:YYYY HH:MM:SS.mmm` — e.g. `31:05:2026 14:30:45.123`.

---

## API endpoints

| Method | Path | Access |
|--------|------|--------|
| `POST` | `/v1/auth/login` | Public |
| `POST` | `/v1/auth/logout` | Authenticated |
| `GET` | `/v1/auth/me` | Authenticated |
| `GET` | `/v1/auth/me/sessions` | Authenticated |
| `POST` | `/v1/companies/` | Super Admin |
| `GET` | `/v1/companies/` | Super Admin |
| `GET` | `/v1/companies/{id}` | Super Admin |
| `PUT` | `/v1/companies/{id}` | Super Admin |
| `DELETE` | `/v1/companies/{id}` | Super Admin |
| `POST` | `/v1/users/` | Admin (own company) |
| `GET` | `/v1/users/` | Admin (own company) |
| `GET` | `/v1/users/{id}` | Admin (own company) |
| `PUT` | `/v1/users/{id}` | Admin (own company) |
| `DELETE` | `/v1/users/{id}` | Admin (own company) |
| `POST` | `/v1/documents/upload` | Admin (own company) |
| `GET` | `/v1/documents/` | Admin (own company) |
| `GET` | `/v1/documents/{id}` | Admin (own company) |
| `DELETE` | `/v1/documents/{id}` | Admin (own company) |
| `POST` | `/v1/chat/invoke` | Admin or Employee |

Interactive docs available at `/docs` when the server is running.

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

## Key design decisions

| Decision | Reason |
|----------|--------|
| **Celery + Redis** for PDF ingestion | Embedding a 100-page PDF takes 10–20 s. Running it in a FastAPI endpoint blocks the event loop and times out clients. Celery processes it in a separate worker process. |
| **pgvector inside PostgreSQL** | Keeps the vector index in the same database as relational data. No separate vector DB to operate, backup, or sync. |
| **REST over GraphQL** | The API is command-driven (upload file, invoke agent). GraphQL shines for flexible data queries; REST is cleaner for file uploads and fire-and-forget async workflows. |
| **LangGraph over a plain LLM call** | Enables a reasoning loop — the LLM can call tools multiple times before answering, which is required for retrieval-augmented generation and chart generation in the same turn. |
| **TokenSession in DB** | Stateless JWTs cannot be revoked. Storing the `jti` lets logout work properly and enables per-session auditing (`ip_address`, `user_agent`, `issued_at`). |
| **Alembic for migrations** | Schema is version-controlled and reproducible. The app refuses to start if `alembic upgrade head` hasn't been run — no silent schema drift. |
| **Pluggable storage backend** | `DOCUMENT_STORAGE=LOCAL` for development; `DOCUMENT_STORAGE=CLOUD_STORAGE` for production S3. The Celery worker, upload endpoint, and delete endpoint all go through the same `StorageBackend` interface — switching backends requires only an env var change. |
| **Structured JSON logging** | Every log line is a JSON object with `ts`, `level`, `logger`, `request_id`, `msg`, and any extra context fields. A `request_id` correlation ID is injected per HTTP request (via middleware) and per Celery task (via task ID), so all log lines for a single operation can be traced across the API and worker. SQL query logging is suppressed unless `LOG_LEVEL=DEBUG`. |

---

## Project structure

```
agentic-rag-api/
├── app/
│   ├── main.py                    # FastAPI app, lifespan startup check, router wiring
│   ├── api/
│   │   ├── dependencies.py        # Auth guards: get_current_user, require_admin, etc.
│   │   └── v1/endpoints/
│   │       ├── auth.py            # login, logout, me, me/sessions
│   │       ├── companies.py       # company CRUD (super admin)
│   │       ├── users.py           # user CRUD (company admin)
│   │       ├── documents.py       # document upload/list/get/delete (company admin)
│   │       └── chat.py            # agent chat invoke (admin + employee)
│   ├── agent/
│   │   ├── graph.py               # LangGraph StateGraph — agent + tool nodes
│   │   └── tools/
│   │       ├── vector_search.py   # pgvector cosine similarity search tool
│   │       └── graph_generator.py # Plotly chart generation tool
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (.env loader)
│   │   ├── security.py            # JWT creation, bcrypt hashing
│   │   ├── logger.py              # JSON structured logging, request-ID ContextVar, setup_logging()
│   │   └── exceptions.py          # AppException hierarchy + global FastAPI exception handlers
│   ├── storage/
│   │   ├── __init__.py            # get_storage() factory — picks LOCAL or S3 backend
│   │   ├── base.py                # abstract StorageBackend interface
│   │   ├── local.py               # LocalStorage — uploads/{company_id}/{stem}_{DD-MM-YYYY_HH-MM-SS}.pdf
│   │   └── s3.py                  # S3Storage — BACKEND/{company_id}/{stem}_{DD-MM-YYYY_HH-MM-SS}.pdf
│   ├── db/
│   │   ├── session.py             # async SQLAlchemy engine and session factory (FastAPI)
│   │   └── models/
│   │       ├── base.py            # declarative Base + ProcessingStatus enum
│   │       ├── company.py         # Company model
│   │       ├── user.py            # User model + UserRole enum
│   │       ├── documents.py       # Document + DocumentChunk models
│   │       └── token_session.py   # TokenSession model
│   ├── schemas/                   # Pydantic request/response models
│   │   ├── common.py              # FormattedDatetime type (DD:MM:YYYY HH:MM:SS.mmm)
│   │   ├── auth.py
│   │   ├── users.py
│   │   ├── companies.py
│   │   ├── documents.py
│   │   ├── sessions.py
│   │   └── chat.py
│   └── worker/
│       ├── celery_app.py          # Celery app config (Redis broker + backend)
│       └── tasks.py               # process_pdf_task (chunk + embed)
├── alembic/
│   ├── env.py                     # async-aware Alembic env
│   ├── script.py.mako             # migration file template
│   └── versions/
│       └── 0001_initial_schema.py # creates vector extension + all 5 tables
├── tests/
├── docker-compose.yml             # PostgreSQL (pgvector) + Redis
├── pyproject.toml                 # uv dependencies
├── uv.lock                        # pinned lockfile (129 packages)
└── alembic.ini                    # Alembic config (URL injected from settings)
```

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
LOCAL_UPLOAD_DIR=uploads   # only used when DOCUMENT_STORAGE=LOCAL

# AWS S3 (only required when DOCUMENT_STORAGE=CLOUD_STORAGE)
# AWS_ACCESS_KEY_ID=
# AWS_SECRET_ACCESS_KEY=
# AWS_REGION=ap-south-1
# S3_BUCKET_NAME=agentic-rag-api
```

---

## Getting started

### 1. Start infrastructure

```bash
docker-compose up -d
```

Starts PostgreSQL 16 with pgvector and Redis.

### 2. Install dependencies

```bash
uv sync
```

### 3. Run database migrations

```bash
alembic upgrade head
```

The app will refuse to start if this step is skipped.

### 4. Start the API server

```bash
uvicorn app.main:app --reload
```

### 5. Start the Celery worker (separate terminal)

On macOS (Apple Silicon), set this first to prevent fork safety issues:

```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

Then:

```bash
celery -A app.worker.celery_app worker --pool=solo --loglevel=info
```

> Use `--pool=prefork` in production (Linux).

---

## Development

### Dependency management

```bash
uv add <package>       # add a dependency
uv remove <package>    # remove a dependency
uv sync                # install/update venv to match uv.lock
```

### Database migrations

```bash
# After changing a model
alembic revision --autogenerate -m "description"
alembic upgrade head

# Roll back one step
alembic downgrade -1
```

### Running tests

```bash
pytest
```

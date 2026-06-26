# Architecture

## Overview

Agentic RAG API is a multi-tenant FastAPI service. Companies upload PDFs; the system ingests
them into a vector database and lets users query the data through a conversational AI agent.

Three separate processes handle different concerns:

| Process | Technology | Responsibility |
|---------|-----------|----------------|
| API server | FastAPI + Uvicorn | HTTP routing, auth, request validation |
| Worker | Celery | PDF ingestion — chunking, embedding, storing vectors |
| Infrastructure | PostgreSQL + Redis | Persistence and task queue |

---

## Component diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│  Client                                                              │
│  (browser / mobile / integration)                                    │
└────────────────────────────┬─────────────────────────────────────────┘
                             │ HTTPS
                             ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FastAPI (Uvicorn)                                                   │
│                                                                      │
│  Middleware                  Routers                                 │
│  ├─ RequestIDMiddleware       ├─ /v1/auth      (public + authed)     │
│  ├─ ExceptionMiddleware       ├─ /v1/companies (super_admin only)    │
│  └─ (Starlette internals)     ├─ /v1/users     (admin + super_admin) │
│                               ├─ /v1/documents (admin + super_admin) │
│                               └─ /v1/chat      (admin + employee)    │
│                                                                      │
│  Dependencies (app/api/dependencies.py)                              │
│  └─ JWT decode → TokenSession lookup → role guard                    │
│                                                                      │
│  Storage abstraction (app/storage/)                                  │
│  └─ LocalStorage | S3Storage  (singleton per process)                │
│                                                                      │
│  Agent (app/agent/)           ← chat endpoint only                  │
│  ├─ LangGraph StateGraph (compiled once at startup)                  │
│  ├─ ChatOllama llama3.1 (singleton)                                  │
│  └─ Tools: search_documents · generate_graph                        │
└────────────┬──────────────────────────────────┬─────────────────────┘
             │                                  │
   Celery    │ .delay()            pgvector      │ SELECT cosine_distance
             ▼                                  ▼
┌────────────────────┐         ┌────────────────────────────────────────┐
│  Redis             │         │  PostgreSQL 16 + pgvector              │
│  (broker+backend)  │         │                                        │
└────────────┬───────┘         │  companies / users / token_sessions   │
             │                 │  documents / document_chunks (384-dim)│
             ▼                 └────────────────────────────────────────┘
┌────────────────────┐                    ▲
│  Celery Worker     │                    │ INSERT chunks
│                    │                    │
│  process_pdf_task  ├────────────────────┘
│  ├─ get PDF from storage
│  ├─ pypdf.PdfReader
│  ├─ RecursiveCharacterTextSplitter (singleton)
│  ├─ HuggingFaceEmbeddings all-MiniLM-L6-v2 (singleton)
│  └─ delete source file from storage
└────────────────────┘
```

---

## Request lifecycle

### 1. Authentication

Every protected endpoint goes through `app/api/dependencies.py`:

```
Client sends JWT
  → jose.jwt.decode (signature + expiry)
  → SELECT TokenSession WHERE jti = ?
     → reject if: row missing | revoked_at set | logout_at set | expired
  → SELECT User WHERE username = sub
  → role guard (require_admin / require_super_admin / require_company_user)
  → return User object to endpoint
```

Token sessions are stored in PostgreSQL so logout is hard (no replay after revoke).

### 2. Document ingestion

```
POST /v1/documents/upload
  → validate admin role + company scope
  → INSERT Document(status=PENDING)
  → storage.upload(file) — writes to LOCAL or S3
  → process_pdf_task.delay(doc_id, storage_ref) — enqueues in Redis
  → return 202

Celery worker (separate process):
  → get_local_path(storage_ref) — S3: download to /tmp; LOCAL: noop
  → PdfReader → full text extraction
  → split text into overlapping chunks (CHUNK_SIZE / CHUNK_OVERLAP)
  → for each chunk: embed_query → 384-dim float vector
  → bulk INSERT DocumentChunk rows
  → UPDATE Document status=COMPLETED
  → storage.delete(storage_ref)
```

### 3. Agent chat

```
POST /v1/chat/invoke { "query": "..." }
  → validate admin/employee role (super_admin blocked)
  → apply recursion limit (8 steps) and per-request duplicate-search guard
  → app_graph.ainvoke({ messages: [HumanMessage] })

  LangGraph loop:
    Agent node (ChatOllama):
      reads conversation history + system prompt
      → decide: answer directly OR call tool

    Tool node (if tool call):
      search_documents(query):
        same-query repetition capped (blocks after one repeat in a request)
        embed_query → cosine_distance SELECT TOP 5 company-scoped document_chunks
      generate_graph(data_json):
        parse JSON → build Plotly figure spec

    → loop back to Agent node until no more tool calls

  → return { response: "...", graph: <plotly payload | null> }
```

---

## Singleton model loading

Expensive objects are initialised **once per process** and reused:

| Object | Where | When loaded |
|--------|-------|-------------|
| `_embeddings_model` (HuggingFace) | `vector_search.py` lazy singleton | First `search_documents` call |
| `llm` (ChatOllama) | `graph.py` module level | FastAPI startup |
| `app_graph` (compiled LangGraph) | `graph.py` module level | FastAPI startup |
| `_embedding_model` (HuggingFace) | `tasks.py` lazy singleton | First Celery task execution |
| `_text_splitter` (RecursiveCharacter) | `tasks.py` lazy singleton | First Celery task execution |
| `_storage` backend | `storage/__init__.py` singleton | First `get_storage()` call |

The Celery worker uses **lazy singletons** because `tasks.py` is imported by the FastAPI
process (to call `.delay()`). Eager loading would waste ~400 MB of model weights in the
API process, which never runs the embedding logic.

To reduce first-request latency, the API performs a best-effort warmup at startup when
`AGENT_WARMUP_ON_STARTUP=true` by preloading the vector-search embedding model.

---

## Storage backends

Controlled by `DOCUMENT_STORAGE` in `.env`. The interface (`StorageBackend`) is the same
for both; only the backend changes.

| Method | LOCAL | CLOUD_STORAGE (S3) |
|--------|-------|---------------------|
| `upload` | Write to `uploads/{company_id}/{stem}_{ts}.pdf` | `s3://agentic-rag-api/BACKEND/{company_id}/{stem}_{ts}.pdf` |
| `get_local_path` | Return path as-is | Download to `/tmp/{filename}` |
| `delete` | `os.remove` | `s3.delete_object` |
| `build_ref` | Reconstruct path from metadata | Reconstruct S3 key from metadata |

`build_ref` is deterministic (metadata only, no I/O) so the delete endpoint can reconstruct
the storage reference from the `Document` row without storing it separately in the database.

---

## Database schema

See [README.md](../README.md) for the full schema table. Key design points:

- All primary keys are UUID strings (generated in Python, not the DB).
- `TIMESTAMPTZ` everywhere; UTC only.
- pgvector `Vector(384)` column on `document_chunks` for cosine distance search.
- Cascade deletes are enforced at the DB level: company → users → sessions, company → documents → chunks.
- `users.company_id` uses `SET NULL` at the FK level, but company deletion in the API path removes child users via ORM cascade.

---

## RBAC model

Four roles define the permission hierarchy:

| Role | Company Affiliation | Permissions |
|------|-------------------|-----------|
| `super_admin` | None (platform operator) | Full cross-company access; can create/manage companies and their first admins; cannot use chat |
| `admin` | Single company | Can create/manage users and documents in their company; can use chat |
| `employee` | Single company | Can use chat only; no management access |
| `guest` (not used) | — | — |

### Data Integrity Constraints

The database enforces a **CHECK constraint** at the table level:

```sql
CHECK (
  (role = 'super_admin' AND company_id IS NULL) 
  OR 
  (role != 'super_admin' AND company_id IS NOT NULL)
)
```

This ensures:
- `super_admin` users **never have a company affiliation** (company_id is always NULL)
- `admin` and `employee` users **always belong to exactly one company**

The constraint is enforced at the database level, preventing accidental cross-role 
assignment at the ORM or application level.

### Role Hierarchy and Access Rules

Enforced in `app/api/dependencies.py`:

**Companies Endpoints (`/v1/companies/`)**
- `super_admin`: full CRUD
- `admin`: no access (403)
- `employee`: no access (403)

**Users Endpoints (`/v1/users/`)**
- `super_admin`: full cross-company CRUD (can create any role except another super_admin)
- `admin`: CRUD users within own company only; cannot promote users to super_admin
- `employee`: no access (403)

**Documents Endpoints (`/v1/documents/`)**
- `super_admin`: full cross-company CRUD; can upload/list/delete any document or filter by company
- `admin`: CRUD documents within own company only
- `employee`: no access (403)

**Chat Endpoint (`/v1/chat/`)**
- `super_admin`: blocked (403) — platform operators do not query documents
- `admin`: full access
- `employee`: full access

### Onboarding Workflow

**Scenario:** A new company joins the platform.

1. **super_admin** creates the company:
   ```
   POST /v1/companies/
   { "name": "Acme Corp", "industry": "Manufacturing", ... }
   ```

2. **super_admin** creates the first company admin (bootstrap only way):
   ```
   POST /v1/users/
   {
     "username": "admin@acme",
     "password": "...",
     "role": "admin",
     "company_id": "<company-uuid>"
   }
   ```

3. **admin@acme** logs in:
   ```
   POST /v1/auth/login
   username=admin@acme&password=...
   ```
   Returns: JWT with claims `role: "admin"`, `company_id: "..."`, `jti: "..."`

4. **admin@acme** creates employees:
   ```
   POST /v1/users/
   {
     "username": "employee1@acme",
     "password": "...",
     "role": "employee",
     "company_id": "<company-uuid>"  // must match their own company
   }
   ```

5. **admin@acme** uploads documents:
   ```
   POST /v1/documents/upload
   file=<PDF>
   // Automatically scoped to admin's company
   ```

6. **employee1@acme** logs in and can query via chat:
   ```
   POST /v1/auth/login
   username=employee1@acme&password=...

   POST /v1/chat/invoke
   { "query": "..." }  // Searches vectors for their company only
   ```

### Critical Security Design

- **No public registration endpoint** — all user creation is admin-controlled (super_admin → admin → employees).
- **JWT sessions tracked in DB** — login creates a `TokenSession` row; logout revokes it; token replay is caught.
- **Cross-company access always 403** — never silent empty results; always explicit error.
- **super_admin cannot be promoted via API** — only created via bootstrap script.
- **Role downgrade is allowed** — an admin can demote themselves to employee, but only `super_admin` can re-promote them to admin.


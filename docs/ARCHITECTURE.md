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
│  ├─ ExceptionMiddleware       ├─ /v1/companies (super_admin)         │
│  └─ (Starlette internals)     ├─ /v1/users     (admin)               │
│                               ├─ /v1/documents (admin)               │
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
  → app_graph.ainvoke({ messages: [HumanMessage] })

  LangGraph loop:
    Agent node (ChatOllama):
      reads conversation history + system prompt
      → decide: answer directly OR call tool

    Tool node (if tool call):
      search_documents(query):
        embed_query → cosine_distance SELECT TOP 5 document_chunks
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
| `embeddings_model` (HuggingFace) | `vector_search.py` module level | FastAPI startup (first import) |
| `llm` (ChatOllama) | `graph.py` module level | FastAPI startup |
| `app_graph` (compiled LangGraph) | `graph.py` module level | FastAPI startup |
| `_embedding_model` (HuggingFace) | `tasks.py` lazy singleton | First Celery task execution |
| `_text_splitter` (RecursiveCharacter) | `tasks.py` lazy singleton | First Celery task execution |
| `_storage` backend | `storage/__init__.py` singleton | First `get_storage()` call |

The Celery worker uses **lazy singletons** because `tasks.py` is imported by the FastAPI
process (to call `.delay()`). Eager loading would waste ~400 MB of model weights in the
API process, which never runs the embedding logic.

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
- `users.company_id` is `SET NULL` on company delete (user record survives).

---

## RBAC model

Three roles, enforced in `app/api/dependencies.py`:

```
super_admin  ─── no company ─── can: create/read/update/delete companies
                                 cannot: access users, documents, chat

admin        ─── company_id ─── can: CRUD users in own company
                              ─── can: CRUD documents in own company
                              ─── can: use chat
                                 cannot: cross-company access (hard 403)

employee     ─── company_id ─── can: use chat only
```

Cross-company access always returns `403 Forbidden`, never a silent empty result.

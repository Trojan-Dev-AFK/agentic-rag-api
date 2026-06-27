# API Documentation

## Overview

The Agentic RAG API follows a **multi-tenant, role-based access control (RBAC)** model. 
Three user roles define permissions:

| Role | Company Affiliation | Permissions |
|------|-------------------|-----------|
| `super_admin` | None (platform operator) | Full cross-company access; can create/manage companies, admins, and employees; **cannot be created/promoted via API** |
| `admin` | Single company | Manage users and documents within their company; can use chat |
| `employee` | Single company | Chat access only; no user/document management |

### Data Integrity Constraint

The database enforces an invariant at the **CHECK constraint** level:
- `super_admin` users **must have** `company_id = NULL`
- `admin` and `employee` users **must have** `company_id != NULL`

This prevents accidental cross-role assignment at the database level.

---

## Authentication Endpoints (`/v1/auth`)

### `POST /v1/auth/login`

**Access:** Public (no JWT required)

Authenticate a user and receive a JWT access token.

**Request:**
```
Content-Type: application/x-www-form-urlencoded

username=alice&password=secret123
```

**Response (200 OK):**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "token_type": "bearer",
  "expires_in": 3600,
  "role": "admin",
  "company_id": "company-uuid-123"
}
```

**Notes:**
- JWT includes `jti` (JWT ID) for tracking sessions in `TokenSession` table
- Token expires after `ACCESS_TOKEN_EXPIRE_MINUTES` (from config)
- Tokens are validated by checking `TokenSession` rows at each protected endpoint

---

### `POST /v1/auth/logout`

**Access:** Authenticated (any user with valid JWT)

Revoke the current token session.

**Request:**
```
Authorization: Bearer <access_token>
```

**Response (200 OK):**
```json
{
  "message": "Successfully logged out"
}
```

**Notes:**
- Sets `logout_at` and `revoked_at` timestamps on the `TokenSession` row
- Subsequent requests with the same token will be rejected

---

### `GET /v1/auth/me`

**Access:** Authenticated (any user with valid JWT)

Retrieve the current user's profile.

**Response (200 OK):**
```json
{
  "id": "user-uuid-456",
  "username": "alice",
  "role": "admin",
  "company_id": "company-uuid-123",
  "company_name": "Acme Corp",
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

### `GET /v1/auth/me/sessions`

**Access:** Authenticated (any user with valid JWT)

List all active token sessions for the current user.

**Response (200 OK):**
```json
[
  {
    "id": "session-uuid-001",
    "user_id": "user-uuid-456",
    "jti": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "issued_at": "2024-01-15T10:30:00Z",
    "expires_at": "2024-01-15T11:30:00Z",
    "revoked_at": null,
    "logout_at": null,
    "ip_address": null,
    "user_agent": null
  }
]
```

---

## User Management Endpoints (`/v1/users`)

### `POST /v1/users/`

**Access:** `admin` (own company) or `super_admin` (any company)

Create a new user (admin or employee) in a company.

**Constraints:**
- Cannot assign `super_admin` role (use bootstrap script for that)
- `admin` can only create users in their own company
- `super_admin` can create users in any company

**Request:**
```json
{
  "username": "bob",
  "password": "newpassword456",
  "role": "employee",
  "company_id": "company-uuid-123"
}
```

**Response (201 Created):**
```json
{
  "id": "user-uuid-789",
  "username": "bob",
  "role": "employee",
  "company_id": "company-uuid-123",
  "company_name": "Acme Corp",
  "created_at": "2024-01-15T10:45:00Z"
}
```

**Errors:**
- `400 Bad Request` — username already registered or company not found
- `403 Forbidden` — insufficient role or cross-company attempt

---

### `GET /v1/users/`

**Access:** `admin` (own company) or `super_admin` (all companies)

List users.

**Query Parameters:**
- `company_id` (optional, string UUID)
  - **admin**: ignored (always returns own company users)
  - **super_admin**: filter by specified company; if omitted, returns all users (excluding other super_admins)

**Response (200 OK):**
```json
[
  {
    "id": "user-uuid-456",
    "username": "alice",
    "role": "admin",
    "company_id": "company-uuid-123",
    "company_name": "Acme Corp",
    "created_at": "2024-01-15T10:30:00Z"
  },
  {
    "id": "user-uuid-789",
    "username": "bob",
    "role": "employee",
    "company_id": "company-uuid-123",
    "company_name": "Acme Corp",
    "created_at": "2024-01-15T10:45:00Z"
  }
]
```

**Errors:**
- `401 Unauthorized` — invalid or missing JWT
- `403 Forbidden` — insufficient role

---

### `GET /v1/users/{user_id}`

**Access:** `admin` (same company) or `super_admin` (any user)

Retrieve a specific user's profile.

**Response (200 OK):**
```json
{
  "id": "user-uuid-789",
  "username": "bob",
  "role": "employee",
  "company_id": "company-uuid-123",
  "company_name": "Acme Corp",
  "created_at": "2024-01-15T10:45:00Z"
}
```

**Errors:**
- `404 Not Found` — user does not exist
- `403 Forbidden` — insufficient role or cross-company attempt

---

### `PUT /v1/users/{user_id}`

**Access:** `admin` (same company) or `super_admin` (any user)

Update a user's password, role, or company assignment.

**Constraints:**
- Cannot promote to `super_admin`
- `admin` can only update users in their own company and cannot move them to a different company
- `super_admin` can reassign users to any company

**Request:**
```json
{
  "password": "updatedpassword789",
  "role": "admin",
  "company_id": "company-uuid-456"
}
```

All fields are optional; only specified fields are updated.

**Response (200 OK):**
```json
{
  "id": "user-uuid-789",
  "username": "bob",
  "role": "admin",
  "company_id": "company-uuid-456",
  "company_name": "Acme Corp North",
  "created_at": "2024-01-15T10:45:00Z"
}
```

**Errors:**
- `404 Not Found` — user does not exist
- `403 Forbidden` — insufficient role, cross-company attempt, or attempted super_admin promotion

---

### `DELETE /v1/users/{user_id}`

**Access:** `admin` (same company) or `super_admin` (any user)

Delete a user account and cascade-delete all their token sessions.

**Constraints:**
- `admin` can only delete users in their own company
- `super_admin` can delete any user

**Response (204 No Content)**

**Errors:**
- `404 Not Found` — user does not exist
- `403 Forbidden` — insufficient role or cross-company attempt

---

### `GET /v1/auth/sessions/company`

**Access:** `admin` (their company) or `super_admin` (optional company filter)

List all token sessions within a company.

**Query Parameters:**
- `company_id` (optional, string UUID)
  - **admin**: may be omitted or equal to their own company; any other value returns `403`
  - **super_admin**: optional filter; if omitted, returns sessions across all company users

**Response (200 OK):**
```json
[
  {
    "id": "session-uuid-001",
    "user_id": "user-uuid-456",
    "jti": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "issued_at": "2024-01-15T10:30:00Z",
    "expires_at": "2024-01-15T11:30:00Z",
    "revoked_at": null,
    "logout_at": null,
    "ip_address": null,
    "user_agent": null
  }
]
```

---

## Company Management Endpoints (`/v1/companies`)

### `POST /v1/companies/`

**Access:** `super_admin` only

Create a new company (tenant).

**Request:**
```json
{
  "name": "Acme Corp",
  "industry": "Manufacturing",
  "description": "Leading industrial solutions provider"
}
```

**Response (201 Created):**
```json
{
  "id": "company-uuid-123",
  "name": "Acme Corp",
  "industry": "Manufacturing",
  "description": "Leading industrial solutions provider",
  "created_at": "2024-01-15T09:00:00Z"
}
```

**Errors:**
- `400 Bad Request` — company name already exists
- `403 Forbidden` — insufficient role

---

### `GET /v1/companies/`

**Access:** `super_admin` only

List all companies.

**Response (200 OK):**
```json
[
  {
    "id": "company-uuid-123",
    "name": "Acme Corp",
    "industry": "Manufacturing",
    "description": "Leading industrial solutions provider",
    "created_at": "2024-01-15T09:00:00Z"
  },
  {
    "id": "company-uuid-456",
    "name": "TechCorp",
    "industry": "Software",
    "description": "Cloud-first SaaS platform",
    "created_at": "2024-01-15T09:15:00Z"
  }
]
```

---

### `GET /v1/companies/{company_id}`

**Access:** `super_admin` only

Retrieve a specific company's details.

**Response (200 OK):**
```json
{
  "id": "company-uuid-123",
  "name": "Acme Corp",
  "industry": "Manufacturing",
  "description": "Leading industrial solutions provider",
  "created_at": "2024-01-15T09:00:00Z"
}
```

**Errors:**
- `404 Not Found` — company does not exist

---

### `PUT /v1/companies/{company_id}`

**Access:** `super_admin` only

Update company details.

**Request:**
```json
{
  "name": "Acme Corp Rebranded",
  "industry": "Diversified Manufacturing",
  "description": "Updated description"
}
```

All fields are optional.

**Response (200 OK):**
```json
{
  "id": "company-uuid-123",
  "name": "Acme Corp Rebranded",
  "industry": "Diversified Manufacturing",
  "description": "Updated description",
  "created_at": "2024-01-15T09:00:00Z"
}
```

---

### `DELETE /v1/companies/{company_id}`

**Access:** `super_admin` only

Delete a company. This cascades to all associated users (their `company_id` → NULL, which violates constraints and may fail).

**Response (204 No Content)**

**Notes:**
- Deleting a company should be rare in production. Consider archiving instead.

---

## Document Management Endpoints (`/v1/documents`)

### `POST /v1/documents/upload`

**Access:** `admin` (own company) or `super_admin` (any company)

Upload a PDF for ingestion and vector embedding.

**Query Parameters:**
- `company_id` (string UUID)
  - **admin**: ignored (always uploads to own company)
  - **super_admin**: required and must reference an existing company

**Request:**
```
Content-Type: multipart/form-data

file=<binary PDF data>
```

**Response (202 Accepted):**
```json
{
  "message": "Document accepted for processing",
  "document_id": "doc-uuid-001",
  "status": "pending"
}
```

**Notes:**
- The file is stored to S3 or local storage
- Celery worker processes asynchronously
- Status will transition: `pending` → `processing` → `completed` or `failed`

**Errors:**
- `400 Bad Request` — company not found
- `403 Forbidden` — insufficient role

---

### `GET /v1/documents/`

**Access:** `admin` (own company) or `super_admin` (any company)

List documents.

**Query Parameters:**
- `company_id` (optional, string UUID)
  - **admin**: ignored (always returns own company documents)
  - **super_admin**: filter by specified company; if omitted, returns all documents

**Response (200 OK):**
```json
[
  {
    "id": "doc-uuid-001",
    "filename": "acme_contracts_2024.pdf",
    "status": "completed",
    "created_at": "2024-01-15T10:15:00Z"
  },
  {
    "id": "doc-uuid-002",
    "filename": "employee_handbook.pdf",
    "status": "processing",
    "created_at": "2024-01-15T10:20:00Z"
  }
]
```

---

### `GET /v1/documents/{document_id}`

**Access:** `admin` (same company) or `super_admin` (any document)

Retrieve a specific document's status and metadata.

**Response (200 OK):**
```json
{
  "id": "doc-uuid-001",
  "filename": "acme_contracts_2024.pdf",
  "status": "completed",
  "created_at": "2024-01-15T10:15:00Z"
}
```

**Document Statuses:**
- `PENDING` — queued for processing
- `PROCESSING` — Celery worker is chunking/embedding
- `COMPLETED` — chunks stored in `document_chunks` table
- `FAILED` — error during processing

**Errors:**
- `404 Not Found` — document does not exist
- `403 Forbidden` — insufficient role or cross-company attempt

---

### `DELETE /v1/documents/{document_id}`

**Access:** `admin` (same company) or `super_admin` (any document)

Delete a document and cascade-delete all its vector chunks from the database.
Also removes the source PDF from storage.

**Response (204 No Content)**

**Errors:**
- `404 Not Found` — document does not exist
- `403 Forbidden` — insufficient role or cross-company attempt

---

## Chat Endpoint (`/v1/chat`)

### `POST /v1/chat/invoke`

**Access:** `admin` and `employee` (company users only); `super_admin` blocked

Invoke the agent with a natural language query. Returns a grounded conversational response.

**Safeguards:**
- LangGraph recursion limit is capped at `8` per request.
- Repeated identical `search_documents` queries are blocked after one repeat to prevent loops.

**Request:**
```json
{
  "query": "What are the key terms in our contracts?",
  "conversation_id": "optional-existing-conversation-uuid"
}
```

**Response (200 OK):**
```json
{
  "response": "Based on the analyzed contracts, the key terms include...",
  "conversation_id": "conversation-uuid-123"
}
```

**Notes:**
- Omit `conversation_id` to create a new persisted conversation.
- Provide `conversation_id` to continue an existing conversation.
- Conversation access is user-scoped and company-scoped.

---

### `GET /v1/chat/conversations`

**Access:** `admin` and `employee` (company users only); `super_admin` blocked

List persisted conversations owned by the authenticated user.

**Response (200 OK):**
```json
[
  {
    "id": "conversation-uuid-123",
    "title": "What are the key terms in our contracts?",
    "created_at": "27:06:2026 10:15:00.123",
    "updated_at": "27:06:2026 10:17:42.100"
  }
]
```

---

### `GET /v1/chat/conversations/{conversation_id}/messages`

**Access:** `admin` and `employee` (company users only); `super_admin` blocked

Return persisted messages for one conversation owned by the authenticated user.

**Response (200 OK):**
```json
[
  {
    "id": "message-uuid-1",
    "conversation_id": "conversation-uuid-123",
    "role": "user",
    "content": "What are the key terms in our contracts?",
    "created_at": "27:06:2026 10:15:00.123"
  },
  {
    "id": "message-uuid-2",
    "conversation_id": "conversation-uuid-123",
    "role": "assistant",
    "content": "Based on the analyzed contracts, the key terms include...",
    "created_at": "27:06:2026 10:15:02.512"
  }
]
```

**Errors:**
- `404 Not Found` — conversation does not exist or does not belong to the authenticated user

**Errors:**
- `502 Bad Gateway` — agent orchestration failed (LLM/tool failure surfaced as `AgentError`)
- `500 Internal Server Error` — unexpected unhandled server error

---

## Error Responses

All endpoints follow standard HTTP status codes and return error details in JSON:

```json
{
  "detail": "User not found"
}
```

### Common Status Codes

| Status | Meaning |
|--------|---------|
| 200 | OK |
| 201 | Created |
| 202 | Accepted (async processing) |
| 204 | No Content (successful DELETE) |
| 400 | Bad Request (validation failed) |
| 401 | Unauthorized (invalid/missing JWT) |
| 403 | Forbidden (role/company insufficient) |
| 404 | Not Found (resource missing) |
| 500 | Internal Server Error |

---

## Onboarding Workflow for a New Company

1. **super_admin** creates the company:
   ```
   POST /v1/companies/
   {
     "name": "New Corp",
     "industry": "...",
     "description": "..."
   }
   ```

2. **super_admin** creates the first company admin:
   ```
   POST /v1/users/
   {
     "username": "admin@newcorp",
     "password": "...",
     "role": "admin",
     "company_id": "<company-uuid>"
   }
   ```

3. **admin@newcorp** logs in:
   ```
   POST /v1/auth/login
   username=admin@newcorp&password=...
   ```

4. **admin@newcorp** creates employees and manages documents:
   ```
   POST /v1/users/
   {
     "username": "employee1@newcorp",
     "password": "...",
     "role": "employee",
     "company_id": "<company-uuid>"
   }
   
   POST /v1/documents/upload
   file=<PDF data>
   ```

5. **employee1@newcorp** logs in and can access chat (query documents).

---

## Bootstrap / Super Admin Creation

The `super_admin` role **cannot** be created or promoted via the API. Instead, use the
bootstrap script:

```bash
python scripts/create_superadmin.py \
  --username superadmin \
  --password <secure-password>
```

This ensures super_admin creation is a controlled, out-of-band process.

---

## JWT Structure

Access tokens are signed JWTs with the following claims:

```json
{
  "sub": "username",
  "role": "admin",
  "company_id": "company-uuid-123",
  "jti": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "iat": 1705339800,
  "exp": 1705343400
}
```

- `sub` — username (unique identifier)
- `role` — `super_admin`, `admin`, or `employee`
- `company_id` — company UUID (NULL for super_admin, set for others)
- `jti` — JWT ID, used to track and revoke sessions
- `iat` — issued at (Unix timestamp)
- `exp` — expiration time (Unix timestamp)

Every protected endpoint validates the JWT signature, checks expiry, and verifies the 
`TokenSession` row exists and hasn't been revoked/logged-out.

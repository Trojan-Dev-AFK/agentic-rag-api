# Endpoint Access Matrix

Quick reference for all API endpoints and their access rules.

## Summary Table

| Endpoint | Method | Public | Employee | Admin | Super Admin | Notes |
|----------|--------|--------|----------|-------|------------|-------|
| **Auth** |
| `/v1/auth/login` | POST | ✅ | ✅ | ✅ | ✅ | Password-based, returns JWT |
| `/v1/auth/logout` | POST | ❌ | ✅ | ✅ | ✅ | Revokes current session |
| `/v1/auth/me` | GET | ❌ | ✅ | ✅ | ✅ | Current user profile |
| `/v1/auth/me/sessions` | GET | ❌ | ✅ | ✅ | ✅ | Own token sessions |
| `/v1/auth/sessions/company` | GET | ❌ | ❌ | ✅* | ✅* | Company/all sessions; * requires matching company_id or query param |
| **Companies** |
| `/v1/companies/` | POST | ❌ | ❌ | ❌ | ✅ | Create tenant |
| `/v1/companies/` | GET | ❌ | ❌ | ❌ | ✅ | List all companies |
| `/v1/companies/{id}` | GET | ❌ | ❌ | ❌ | ✅ | Get company details |
| `/v1/companies/{id}` | PUT | ❌ | ❌ | ❌ | ✅ | Update company |
| `/v1/companies/{id}` | DELETE | ❌ | ❌ | ❌ | ✅ | Delete company |
| **Users** |
| `/v1/users/` | POST | ❌ | ❌ | ✅* | ✅ | Create user; * own company only |
| `/v1/users/` | GET | ❌ | ❌ | ✅* | ✅ | List users; * own company only |
| `/v1/users/{id}` | GET | ❌ | ❌ | ✅* | ✅ | Get user; * own company only |
| `/v1/users/{id}` | PUT | ❌ | ❌ | ✅* | ✅ | Update user; * own company only |
| `/v1/users/{id}` | DELETE | ❌ | ❌ | ✅* | ✅ | Delete user; * own company only |
| **Documents** |
| `/v1/documents/upload` | POST | ❌ | ❌ | ✅* | ✅ | Upload PDF; * own company only |
| `/v1/documents/` | GET | ❌ | ❌ | ✅* | ✅ | List documents; * own company only |
| `/v1/documents/{id}` | GET | ❌ | ❌ | ✅* | ✅ | Get document; * own company only |
| `/v1/documents/{id}` | DELETE | ❌ | ❌ | ✅* | ✅ | Delete document; * own company only |
| **Chat** |
| `/v1/chat/invoke` | POST | ❌ | ✅ | ✅ | ❌ | Query agent; super_admin blocked |

**Legend:**
- ✅ = full access
- ❌ = no access (403 Forbidden)
- ✅* = access scoped to own company or resource

---

## Detailed Access Rules

### Auth Endpoints

| Endpoint | Super Admin | Admin | Employee | Details |
|----------|-------------|-------|----------|---------|
| `POST /v1/auth/login` | ✅ public | ✅ public | ✅ public | No JWT required; username/password auth |
| `POST /v1/auth/logout` | ✅ JWT | ✅ JWT | ✅ JWT | Revokes `TokenSession` row |
| `GET /v1/auth/me` | ✅ JWT | ✅ JWT | ✅ JWT | Returns user profile |
| `GET /v1/auth/me/sessions` | ✅ JWT | ✅ JWT | ✅ JWT | Lists user's token sessions |
| `GET /v1/auth/sessions/company` | ✅ JWT (all or filter by query param) | ✅ JWT (own company only) | ❌ | Lists company's sessions |

### Company Endpoints

All require **super_admin role**. No company scoping (super_admin is unaffiliated).

| Endpoint | Accessible By | Notes |
|----------|---------------|-------|
| `POST /v1/companies/` | super_admin | Create new tenant |
| `GET /v1/companies/` | super_admin | List all companies |
| `GET /v1/companies/{id}` | super_admin | Get specific company |
| `PUT /v1/companies/{id}` | super_admin | Update company metadata |
| `DELETE /v1/companies/{id}` | super_admin | Delete company (rare) |

### User Endpoints

Scoped by company (admins see own company only; super_admin sees all).

| Endpoint | Super Admin | Admin | Employee | Notes |
|----------|-------------|-------|----------|-------|
| `POST /v1/users/` | ✅ any company | ✅ own company only | ❌ | Cannot assign super_admin role |
| `GET /v1/users/` | ✅ all or filtered by `?company_id=` | ✅ own company only | ❌ | Query param ignored for admin |
| `GET /v1/users/{id}` | ✅ any user | ✅ own company only | ❌ | |
| `PUT /v1/users/{id}` | ✅ any user, can move between companies | ✅ own company only, cannot move | ❌ | Cannot promote to super_admin |
| `DELETE /v1/users/{id}` | ✅ any user | ✅ own company only | ❌ | Cascades to TokenSessions |

### Document Endpoints

Scoped by company (admins see own company only; super_admin sees all).

| Endpoint | Super Admin | Admin | Employee | Notes |
|----------|-------------|-------|----------|-------|
| `POST /v1/documents/upload` | ✅ any company (optional `?company_id=`) | ✅ own company only | ❌ | Files stored with company_id prefix |
| `GET /v1/documents/` | ✅ all or filtered by `?company_id=` | ✅ own company only | ❌ | Query param ignored for admin |
| `GET /v1/documents/{id}` | ✅ any document | ✅ own company only | ❌ | Returns 403 if cross-company |
| `DELETE /v1/documents/{id}` | ✅ any document | ✅ own company only | ❌ | Cascades to chunks; removes storage file |

### Chat Endpoint

Employees and admins only (super_admin explicitly blocked).

| Endpoint | Super Admin | Admin | Employee | Notes |
|----------|-------------|-------|----------|-------|
| `POST /v1/chat/invoke` | ❌ 403 | ✅ | ✅ | Searches vectors scoped to company |

---

## Cross-Company Access Behavior

**Always returns `403 Forbidden`, never silently succeeds or returns empty:**

1. **admin@acme** tries to read **user@techcorp**:
   ```
   GET /v1/users/techcorp-user-uuid
   → 403 Forbidden: "Access denied"
   ```

2. **admin@acme** tries to access **techcorp**'s document:
   ```
   GET /v1/documents/techcorp-doc-uuid
   → 403 Forbidden: "Access denied"
   ```

3. **admin@acme** tries to list **techcorp**'s sessions:
   ```
   GET /v1/auth/sessions/company?company_id=techcorp-uuid
   → 403 Forbidden: "Access denied"
   ```

This design prevents accidental data leaks through query parameters or enumeration attacks.

---

## JWT Claims and Token Validation

Every protected endpoint validates:

1. **JWT Signature** — valid according to SECRET_KEY and algorithm
2. **Expiry** — `exp` claim not in the past
3. **TokenSession Row** — exists, not revoked, not logged out
4. **Role** — matches required role for the endpoint

Example JWT payload:
```json
{
  "sub": "alice",
  "role": "admin",
  "company_id": "acme-uuid-123",
  "jti": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
  "iat": 1705339800,
  "exp": 1705343400
}
```

If any check fails, the endpoint returns `401 Unauthorized`.

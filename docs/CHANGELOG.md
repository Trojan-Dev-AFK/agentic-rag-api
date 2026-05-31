# Changelog: Enterprise Auth & Multi-Tenant RBAC

## Summary of Changes

This document tracks all changes made to implement a secure, enterprise-grade multi-tenant 
RBAC system with super_admin support.

---

## 1. Database Schema Updates

### User Model (`app/db/models/user.py`)

**Added:**
- `CheckConstraint` to enforce data integrity:
  ```
  (role = 'super_admin' AND company_id IS NULL) 
  OR 
  (role != 'super_admin' AND company_id IS NOT NULL)
  ```

**Effect:** Database prevents invalid user/company combinations at the table level.

---

## 2. API Endpoint Changes

### Auth Endpoints (`/v1/auth`)

| Endpoint | Change | Details |
|----------|--------|---------|
| `POST /v1/auth/login` | Unchanged | Public login; returns JWT with `jti` |
| `POST /v1/auth/logout` | Unchanged | Authenticated; revokes `TokenSession` |
| `GET /v1/auth/me` | Unchanged | Authenticated; returns user profile |
| `GET /v1/auth/me/sessions` | **Moved from `/v1/users`** | Lists current user's sessions |
| `GET /v1/auth/sessions/company` | Unchanged | Lists company's sessions (admin + super_admin) |

### User Endpoints (`/v1/users`)

| Endpoint | Before | After | Notes |
|----------|--------|-------|-------|
| `POST /v1/users/` | `admin` only | `admin` + `super_admin` | super_admin can create in any company |
| `GET /v1/users/` | `admin` only | `admin` + `super_admin` | super_admin can filter by company_id |
| `GET /v1/users/{id}` | `admin` only | `admin` + `super_admin` | super_admin can access any user |
| `PUT /v1/users/{id}` | `admin` only | `admin` + `super_admin` | super_admin can move users between companies |
| `DELETE /v1/users/{id}` | `admin` only | `admin` + `super_admin` | super_admin can delete any user |

**Removed:**
- Public `/v1/users/register` endpoint (admin-controlled only)

### Document Endpoints (`/v1/documents`)

| Endpoint | Before | After | Notes |
|----------|--------|-------|-------|
| `POST /v1/documents/upload` | `require_admin` | `require_admin_or_super_admin` | super_admin can upload for any company via `?company_id=` |
| `GET /v1/documents/` | `require_admin` | `require_admin_or_super_admin` | super_admin can filter by company_id |
| `GET /v1/documents/{id}` | `require_admin` | `require_admin_or_super_admin` | super_admin can access any document |
| `DELETE /v1/documents/{id}` | `require_admin` | `require_admin_or_super_admin` | super_admin can delete any document |

### Company Endpoints (`/v1/companies`)

| Endpoint | Before | After | Notes |
|----------|--------|-------|-------|
| `POST /v1/companies/` | `require_super_admin` | Unchanged | super_admin only |
| `GET /v1/companies/` | `require_super_admin` | Unchanged | super_admin only |
| `GET /v1/companies/{id}` | `require_super_admin` | Unchanged | super_admin only |
| `PUT /v1/companies/{id}` | `require_super_admin` | Unchanged | super_admin only |
| `DELETE /v1/companies/{id}` | `require_super_admin` | Unchanged | super_admin only |

### Chat Endpoint

| Endpoint | Before | After | Notes |
|----------|--------|-------|-------|
| `POST /v1/chat/invoke` | Allows `admin` + `employee` | Unchanged (blocks `super_admin`) | super_admin cannot query documents |

---

## 3. Dependency Injection Updates

### `app/api/dependencies.py`

**Existing Guards:**
- `get_current_user()` — decodes JWT, validates TokenSession, returns User
- `require_admin()` — requires `role == admin` with valid `company_id`
- `require_super_admin()` — requires `role == super_admin`
- `require_company_user()` — allows `admin` or `employee` (blocks `super_admin`)

**Used By:**
- Auth endpoints → `get_current_user`
- User/Document endpoints → `require_admin_or_super_admin`
- Company endpoints → `require_super_admin`
- Chat endpoint → `require_company_user` (blocks super_admin)

---

## 4. Router Registration

### `app/main.py`

**Before:**
```python
app.include_router(chat.router, prefix="/v1/chat", tags=["Agent"])
app.include_router(documents.router, prefix="/v1/documents", tags=["Documents"])
app.include_router(companies.router, prefix="/v1/companies", tags=["Companies"])
app.include_router(users.router, prefix="/v1/users", tags=["Users"])
```

**After:**
```python
app.include_router(auth.router, prefix="/v1/auth", tags=["Auth"])
app.include_router(chat.router, prefix="/v1/chat", tags=["Agent"])
app.include_router(documents.router, prefix="/v1/documents", tags=["Documents"])
app.include_router(companies.router, prefix="/v1/companies", tags=["Companies"])
app.include_router(users.router, prefix="/v1/users", tags=["Users"])
```

**Change:** Re-added `/v1/auth` router (was consolidated into `/v1/users`; now split again for clarity).

---

## 5. Request Logging

All protected endpoints now log:
- Actor (current_user.id, role)
- Action (what was created/updated/deleted)
- Target (resource IDs, company_id)
- Outcome (success/denial reason)

Example:
```python
logger.info(
    "User created",
    extra={
        "user_id": new_user.id,
        "username": new_user.username,
        "role": str(new_user.role),
        "company_id": new_user.company_id,
        "actor": current_user.id,
        "actor_role": str(current_user.role),
    },
)
```

---

## 6. Documentation

**New Files:**
- `docs/API_DOCS.md` — Complete endpoint reference with examples
- `docs/ENDPOINT_ACCESS_MATRIX.md` — Quick reference for access rules
- `docs/CHANGELOG.md` — This file

**Updated:**
- `docs/ARCHITECTURE.md` — Added RBAC model, onboarding workflow, data integrity constraints

---

## 7. Onboarding Workflow (Updated)

**Before:** No way to create the first admin (chicken-and-egg problem).

**After:**
1. `super_admin` (bootstrap script only) creates company
2. `super_admin` creates first company admin
3. Company admin creates employees
4. Employees use chat

**Bootstrap Super Admin:**
```bash
python scripts/create_superadmin.py --username superadmin --password secure
```

---

## 8. Key Design Decisions

### Why Super Admin Has No Company

- **Separation of Concerns:** Platform operator ≠ customer operator
- **Simplicity:** Avoids dual-role scenarios (super_admin managing their "own" company)
- **Security:** Explicit boundary between platform and customer namespaces
- **Database Integrity:** CHECK constraint enforces this at the table level

### Why No Public Registration

- **Enterprise Model:** Companies are invited/onboarded by platform
- **Security:** Prevents account enumeration or unauthorized access
- **Auditability:** Every account creation is traceable to an admin

### Why JWT Sessions are Tracked in DB

- **Hard Logout:** Revoke without waiting for expiry
- **Audit Trail:** Know exactly when users logged in/out
- **Revocation:** Immediate across all processes (no cache issues)
- **Session Limits:** Future: limit active sessions per user

### Why Super Admin is Blocked from Chat

- **Data Segmentation:** Super admin shouldn't need to read customer data
- **Audit Clarity:** All document access is scoped to company users
- **Compliance:** Easier to implement data residency/compliance rules

---

## 9. Testing Checklist

- [ ] `super_admin` can create company
- [ ] `super_admin` can create admin in any company
- [ ] `super_admin` cannot create another `super_admin` via API
- [ ] `admin` can create employees in own company only
- [ ] `admin` cannot create users in other companies (403)
- [ ] `employee` cannot access user/document CRUD (403)
- [ ] `super_admin` blocked from chat (403)
- [ ] Cross-company access always returns 403 (never empty)
- [ ] Logout revokes token immediately
- [ ] Token replay after logout is rejected
- [ ] Deleted company cascades to delete users/sessions
- [ ] CHECK constraint enforced by database

---

## 10. Migration Notes

If upgrading from a previous version:

1. **Database:** Run Alembic migration to add CHECK constraint
2. **Routing:** Re-import `auth` router in `app/main.py`
3. **Environment:** Ensure `SECRET_KEY`, `ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES` are set
4. **Bootstrap:** Run `scripts/create_superadmin.py` to create platform operator

---

## 11. Security Audit

**✅ Implemented:**
- JWT signature validation
- TokenSession hard revocation
- Role-based access control (RBAC)
- Company scoping with 403 on cross-company access
- Database-level constraints
- Audit logging on sensitive operations
- No public registration

**🔲 Future:**
- Rate limiting (login attempts, API calls)
- IP address tracking in TokenSession
- User agent tracking for suspicious changes
- Suspicious login alerting
- Session limits per user
- MFA for super_admin
- API key authentication for service accounts

# Changelog

Project history up to 2026-06-27.

## 2026-06-27

### Added

- Persisted chat history support.
- New database tables:
  - `chat_conversations`
  - `chat_messages`
- New enum type: `chatmessagerole` (`user`, `assistant`).
- New chat endpoints:
  - `GET /v1/chat/conversations`
  - `GET /v1/chat/conversations/{conversation_id}/messages`
- Conversation-aware chat invoke:
  - `POST /v1/chat/invoke` now accepts optional `conversation_id`.
  - Response now includes `conversation_id`.

### Changed

- Chat service now:
  - Creates a new conversation when `conversation_id` is absent.
  - Validates user/company ownership when `conversation_id` is provided.
  - Loads prior turns into graph input context.
  - Persists both user and assistant turns for every invoke.
- Startup schema verification now requires chat history tables.

### Database

- Added migration `0005_add_chat_history_tables.py`.
- Applied migration path now includes `0001 -> 0005`.

### Testing

- Added/updated unit and integration tests for conversation persistence and retrieval.

---

## 2026-06-27 (Earlier)

### Added

- OCR-aware ingestion support for scanned/image-based PDFs.
- New `ChunkType` value: `OCR`.
- New migration `0004_add_ocr_chunk_type.py`.
- New runtime dependencies:
  - `rapidocr-onnxruntime`
  - `pypdfium2`

### Changed

- Worker ingestion pipeline now uses layered extraction:
  1. `pdfplumber` text extraction
  2. `pdfplumber` table extraction
  3. OCR fallback (RapidOCR on pypdfium2-rendered pages lacking extractable text/table content)
  4. Final text fallback via `pypdf`
- Chunk persistence now stores provenance in `document_chunks.chunk_type` as:
  - `TEXT`
  - `TABLE`
  - `OCR`
- Vector search formatting now annotates retrieval context with chunk-source labels:
  - `[TABLE]`
  - `[OCR]`

### Observability

- Added extraction/chunk metrics for text, table, and OCR outputs.

---

## 2026-06-27 (RBAC + Service Layer + Quality Hardening)

### Added

- Service-layer architecture for endpoint business logic:
  - `auth_service`
  - `users_service`
  - `companies_service`
  - `documents_service`
  - `chat_service`
- Thin-endpoint lint rule:
  - `scripts/lint_thin_endpoints.py`
- Expanded automated quality gates:
  - Ruff (including complexity and commented-code checks)
  - Black check
  - Interrogate
  - Vulture
  - Thin-endpoint lint
  - Pytest
- Unit test suite for services.
- Integration tests for role/scoping behavior across key endpoints.

### Changed

- API endpoints refactored to thin transport controllers delegating to services.
- Startup warmup moved to application startup path.
- Node 20 GitHub Actions references updated to current action versions.
- CI test bootstrap improved by setting required environment defaults before app import.

### Fixed

- Document deletion logging crash from reserved LogRecord key collision (`filename` in logger `extra`).
  - Renamed key to `document_filename`.

---

## 2026-06-27 (Graph Simplification)

### Removed

- Graph generation feature and all fallbacks/reference paths.
- Warmup endpoint in favor of startup warmup.

### Kept

- Document-semantic search tool (`search_documents`) as the chat grounding mechanism.

---

## Notes

- Current role model remains:
  - `super_admin`: platform operations only (no chat)
  - `admin`: company-scoped management + chat
  - `employee`: company-scoped chat
- Cross-company access remains explicit `403` behavior.
- Token sessions remain DB-backed for hard logout/revocation semantics.

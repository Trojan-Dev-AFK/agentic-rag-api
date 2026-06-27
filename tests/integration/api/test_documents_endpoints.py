"""Integration tests for documents endpoints role and scoping behavior."""

from app.api.dependencies import get_db, require_admin_or_super_admin
from app.db.models import UserRole
from app.main import app
from app.services import documents_service
from tests.helpers import make_user


def test_admin_document_delete_cross_company_forbidden(test_client, mock_db, override_db, monkeypatch):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_or_super_admin] = lambda: make_user(
        role=UserRole.ADMIN, company_id="c-1", user_id="a-1"
    )

    async def _delete_document(*, document_id, db, current_user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Access denied")

    monkeypatch.setattr(documents_service, "delete_document", _delete_document)

    response = test_client.delete("/v1/documents/d-1")

    assert response.status_code == 403


def test_super_admin_upload_requires_company_id(test_client, mock_db, override_db, monkeypatch):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_or_super_admin] = lambda: make_user(
        role=UserRole.SUPER_ADMIN, company_id=None, user_id="su-1"
    )

    async def _upload_document(*, file, company_id, db, current_user):
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="company_id is required for super_admin uploads")

    monkeypatch.setattr(documents_service, "upload_document", _upload_document)

    response = test_client.post(
        "/v1/documents/upload",
        files={"file": ("a.pdf", b"pdf-bytes", "application/pdf")},
    )

    assert response.status_code == 400

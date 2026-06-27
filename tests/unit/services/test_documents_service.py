"""Unit tests for documents service business logic."""

import asyncio

import pytest
from fastapi import HTTPException

from app.db.models import Document, ProcessingStatus, UserRole
from app.services import documents_service
from tests.helpers import make_user, scalar_result


def test_upload_document_super_admin_missing_company_raises_400(mock_db):
    super_admin = make_user(role=UserRole.SUPER_ADMIN, company_id=None, user_id="su-1")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            documents_service.upload_document(
                file=type("F", (), {"filename": "a.pdf", "content_type": "application/pdf"})(),
                company_id=None,
                db=mock_db,
                current_user=super_admin,
            )
        )

    assert exc_info.value.status_code == 400


def test_get_document_admin_cross_company_raises_403(mock_db):
    admin = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="a-1")
    doc = Document(id="d-1", filename="a.pdf", company_id="other", status=ProcessingStatus.PENDING)
    mock_db.execute.return_value = scalar_result(doc)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(documents_service.get_document(document_id="d-1", db=mock_db, current_user=admin))

    assert exc_info.value.status_code == 403


def test_delete_document_not_found_raises_404(mock_db):
    admin = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="a-1")
    mock_db.execute.return_value = scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(documents_service.delete_document(document_id="d-x", db=mock_db, current_user=admin))

    assert exc_info.value.status_code == 404

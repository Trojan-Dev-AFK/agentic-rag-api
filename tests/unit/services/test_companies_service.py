"""Unit tests for companies service business logic."""

import asyncio

import pytest
from fastapi import HTTPException

from app.db.models import Company, UserRole
from app.schemas.companies import CompanyCreate, CompanyUpdate
from app.services import companies_service
from tests.helpers import make_user, scalar_result


def test_create_company_duplicate_name_raises_400(mock_db):
    current_user = make_user(role=UserRole.SUPER_ADMIN, user_id="su-1")
    mock_db.execute.return_value = scalar_result(Company(name="Acme"))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            companies_service.create_company(
                company_data=CompanyCreate(name="Acme"),
                db=mock_db,
                current_user=current_user,
            )
        )

    assert exc_info.value.status_code == 400


def test_update_company_not_found_raises_404(mock_db):
    current_user = make_user(role=UserRole.SUPER_ADMIN, user_id="su-1")
    mock_db.execute.return_value = scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            companies_service.update_company(
                company_id="missing",
                update_data=CompanyUpdate(name="New"),
                db=mock_db,
                current_user=current_user,
            )
        )

    assert exc_info.value.status_code == 404


def test_delete_company_success(mock_db):
    current_user = make_user(role=UserRole.SUPER_ADMIN, user_id="su-1")
    company = Company(id="c-1", name="Acme")
    mock_db.execute.return_value = scalar_result(company)

    asyncio.run(companies_service.delete_company(company_id="c-1", db=mock_db, current_user=current_user))

    assert mock_db.delete.await_count == 1
    assert mock_db.commit.await_count == 1

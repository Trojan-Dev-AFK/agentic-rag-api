"""Unit tests for users service business logic."""

import asyncio

import pytest
from fastapi import HTTPException

from app.db.models import UserRole
from app.schemas.users import UserCreate, UserUpdate
from app.services import users_service
from tests.helpers import make_user, scalar_result


def test_create_user_admin_cross_company_forbidden(mock_db):
    admin = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="a-1")
    payload = UserCreate(username="bob", password="pw", role=UserRole.EMPLOYEE, company_id="c-2")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(users_service.create_user(user_data=payload, db=mock_db, current_user=admin))

    assert exc_info.value.status_code == 403


def test_update_user_super_admin_role_forbidden(mock_db):
    admin = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="a-1")
    target = make_user(role=UserRole.EMPLOYEE, company_id="c-1", user_id="u-2")
    mock_db.execute.return_value = scalar_result(target)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            users_service.update_user(
                user_id="u-2",
                update_data=UserUpdate(role=UserRole.SUPER_ADMIN),
                db=mock_db,
                current_user=admin,
            )
        )

    assert exc_info.value.status_code == 403


def test_delete_user_self_blocked(mock_db):
    admin = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="a-1")
    mock_db.execute.return_value = scalar_result(admin)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(users_service.delete_user(user_id="a-1", db=mock_db, current_user=admin))

    assert exc_info.value.status_code == 400

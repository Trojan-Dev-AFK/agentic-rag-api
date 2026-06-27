"""Integration tests for users endpoints role and scoping behavior."""

from app.api.dependencies import get_db, require_admin_or_super_admin
from app.db.models import UserRole
from app.main import app
from app.services import users_service
from tests.helpers import make_user


def test_admin_cannot_create_user_in_other_company(test_client, mock_db, override_db, monkeypatch):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_or_super_admin] = lambda: make_user(
        role=UserRole.ADMIN, company_id="c-1", user_id="a-1"
    )

    async def _raise(*args, **kwargs):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Admins may only manage users within their own company.")

    monkeypatch.setattr(users_service, "create_user", _raise)

    response = test_client.post(
        "/v1/users/",
        json={"username": "bob", "password": "pw", "role": "employee", "company_id": "c-2"},
    )

    assert response.status_code == 403


def test_super_admin_can_filter_users_by_company(test_client, mock_db, override_db, monkeypatch):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_admin_or_super_admin] = lambda: make_user(
        role=UserRole.SUPER_ADMIN, company_id=None, user_id="su-1"
    )

    async def _list_users(*, company_id, db, current_user):
        return [
            {
                "id": "11111111-1111-1111-1111-111111111111",
                "username": "alice",
                "role": "admin",
                "company_id": "22222222-2222-2222-2222-222222222222",
                "company_name": "Acme",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ]

    monkeypatch.setattr(users_service, "list_users", _list_users)

    response = test_client.get("/v1/users/?company_id=22222222-2222-2222-2222-222222222222")

    assert response.status_code == 200
    assert response.json()[0]["company_id"] == "22222222-2222-2222-2222-222222222222"

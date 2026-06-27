"""Integration tests for chat endpoint role and scoping behavior."""

from app.api.dependencies import require_company_user
from app.db.models import UserRole
from app.main import app
from app.services import chat_service
from tests.helpers import make_user


def test_chat_denies_user_without_company_scope(test_client, monkeypatch):
    app.dependency_overrides[require_company_user] = lambda: make_user(
        role=UserRole.ADMIN, company_id=None, user_id="u-1"
    )

    async def _invoke_agent(*, query, current_user):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")

    monkeypatch.setattr(chat_service, "invoke_agent", _invoke_agent)

    response = test_client.post("/v1/chat/invoke", json={"query": "hello"})

    assert response.status_code == 403


def test_chat_success_path(test_client, monkeypatch):
    app.dependency_overrides[require_company_user] = lambda: make_user(
        role=UserRole.ADMIN, company_id="c-1", user_id="u-1"
    )

    async def _invoke_agent(*, query, current_user):
        return "answer"

    monkeypatch.setattr(chat_service, "invoke_agent", _invoke_agent)

    response = test_client.post("/v1/chat/invoke", json={"query": "hello"})

    assert response.status_code == 200
    assert response.json()["response"] == "answer"

"""Integration tests for chat endpoint role and scoping behavior."""

from datetime import UTC, datetime

from app.api.dependencies import require_company_user
from app.db.models import UserRole
from app.db.session import get_db
from app.main import app
from app.services import chat_service
from tests.helpers import make_user


def test_chat_denies_user_without_company_scope(test_client, monkeypatch, override_db):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_company_user] = lambda: make_user(
        role=UserRole.ADMIN, company_id=None, user_id="u-1"
    )

    async def _invoke_agent(*, query, current_user, db, conversation_id):
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="You do not have permission to perform this action.")

    monkeypatch.setattr(chat_service, "invoke_agent", _invoke_agent)

    response = test_client.post("/v1/chat/invoke", json={"query": "hello"})

    assert response.status_code == 403


def test_chat_success_path(test_client, monkeypatch, override_db):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_company_user] = lambda: make_user(
        role=UserRole.ADMIN, company_id="c-1", user_id="u-1"
    )

    async def _invoke_agent(*, query, current_user, db, conversation_id):
        return "answer", "conv-1"

    monkeypatch.setattr(chat_service, "invoke_agent", _invoke_agent)

    response = test_client.post("/v1/chat/invoke", json={"query": "hello"})

    assert response.status_code == 200
    assert response.json()["response"] == "answer"
    assert response.json()["conversation_id"] == "conv-1"


def test_list_conversations_success_path(test_client, monkeypatch, override_db):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_company_user] = lambda: make_user(
        role=UserRole.ADMIN, company_id="c-1", user_id="u-1"
    )

    async def _list_conversations(*, db, current_user):
        return [
            {
                "id": "conv-1",
                "title": "hello",
                "created_at": datetime.now(UTC),
                "updated_at": datetime.now(UTC),
            }
        ]

    monkeypatch.setattr(chat_service, "list_conversations", _list_conversations)

    response = test_client.get("/v1/chat/conversations")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "conv-1"


def test_get_conversation_messages_success_path(test_client, monkeypatch, override_db):
    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[require_company_user] = lambda: make_user(
        role=UserRole.ADMIN, company_id="c-1", user_id="u-1"
    )

    async def _get_messages(*, conversation_id, db, current_user):
        return [
            {
                "id": "m-1",
                "conversation_id": conversation_id,
                "query": "hello",
                "response": "hi",
                "created_at": datetime.now(UTC),
            }
        ]

    monkeypatch.setattr(chat_service, "get_conversation_messages", _get_messages)

    response = test_client.get("/v1/chat/conversations/conv-1/messages")

    assert response.status_code == 200
    assert response.json()[0]["conversation_id"] == "conv-1"

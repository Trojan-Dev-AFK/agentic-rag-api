"""Unit tests for chat service business logic."""

import asyncio
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

from app.core.exceptions import AgentError
from app.db.models import ChatConversation, ChatMessage, UserRole
from app.services import chat_service
from tests.helpers import list_result, make_user, scalar_result


def test_invoke_agent_blocks_user_without_company():
    user = make_user(role=UserRole.ADMIN, company_id=None, user_id="u-1")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            chat_service.invoke_agent(
                query="hello",
                current_user=user,
                db=None,
                conversation_id=None,
            )
        )

    assert exc_info.value.status_code == 403


def test_invoke_agent_wraps_recursion_error(monkeypatch):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    mock_db = type("DB", (), {})()
    mock_db.add = lambda _x: None
    mock_db.commit = _async_noop
    mock_db.refresh = _async_noop
    mock_db.execute = _async_execute(
        [
            list_result([]),
        ]
    )

    async def _raise(*args, **kwargs):
        from langgraph.errors import GraphRecursionError

        raise GraphRecursionError("loop")

    monkeypatch.setattr(chat_service.app_graph, "ainvoke", _raise)

    with pytest.raises(AgentError):
        asyncio.run(
            chat_service.invoke_agent(
                query="hello",
                current_user=user,
                db=mock_db,
                conversation_id=None,
            )
        )


def test_invoke_agent_returns_string_message(monkeypatch):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    mock_db = type("DB", (), {})()
    mock_db.add = lambda _x: None
    mock_db.commit = _async_noop
    mock_db.refresh = _async_noop
    mock_db.execute = _async_execute(
        [
            list_result([]),
        ]
    )

    async def _ok(*args, **kwargs):
        return {"messages": [type("M", (), {"content": 123})()]}

    monkeypatch.setattr(chat_service.app_graph, "ainvoke", _ok)

    response, conversation_id = asyncio.run(
        chat_service.invoke_agent(
            query="hello",
            current_user=user,
            db=mock_db,
            conversation_id=None,
        )
    )
    assert response == "123"
    assert isinstance(conversation_id, str)


def test_list_conversations_returns_user_scoped_rows(mock_db):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    conv = ChatConversation(
        id="conv-1",
        user_id="u-1",
        company_id="c-1",
        title="hello",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    mock_db.execute.return_value = list_result([conv])

    rows = asyncio.run(chat_service.list_conversations(db=mock_db, current_user=user))

    assert len(rows) == 1
    assert rows[0].id == "conv-1"


def test_get_conversation_messages_not_found_raises_404(mock_db):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    mock_db.execute.return_value = scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_service.get_conversation_messages(conversation_id="missing", db=mock_db, current_user=user))

    assert exc_info.value.status_code == 404


def test_get_conversation_messages_returns_rows(mock_db):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    conv = ChatConversation(
        id="conv-1",
        user_id="u-1",
        company_id="c-1",
        title="hello",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    msg = ChatMessage(
        id="m-1",
        conversation_id="conv-1",
        user_query="hello",
        assistant_response="hi",
        created_at=datetime.now(UTC),
    )
    mock_db.execute.side_effect = [scalar_result(conv), list_result([msg])]

    rows = asyncio.run(chat_service.get_conversation_messages(conversation_id="conv-1", db=mock_db, current_user=user))

    assert len(rows) == 1
    assert rows[0].query == "hello"
    assert rows[0].response == "hi"


async def _async_noop(*_args, **_kwargs):
    return None


def _async_execute(results):
    iterator = iter(results)

    async def _run(*_args, **_kwargs):
        return next(iterator)

    return _run

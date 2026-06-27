"""Unit tests for chat service business logic."""

import asyncio

import pytest
from fastapi import HTTPException

from app.core.exceptions import AgentError
from app.db.models import UserRole
from app.services import chat_service
from tests.helpers import make_user


def test_invoke_agent_blocks_user_without_company():
    user = make_user(role=UserRole.ADMIN, company_id=None, user_id="u-1")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(chat_service.invoke_agent(query="hello", current_user=user))

    assert exc_info.value.status_code == 403


def test_invoke_agent_wraps_recursion_error(monkeypatch):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")

    async def _raise(*args, **kwargs):
        from langgraph.errors import GraphRecursionError

        raise GraphRecursionError("loop")

    monkeypatch.setattr(chat_service.app_graph, "ainvoke", _raise)

    with pytest.raises(AgentError):
        asyncio.run(chat_service.invoke_agent(query="hello", current_user=user))


def test_invoke_agent_returns_string_message(monkeypatch):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")

    async def _ok(*args, **kwargs):
        return {"messages": [type("M", (), {"content": 123})()]}

    monkeypatch.setattr(chat_service.app_graph, "ainvoke", _ok)

    response = asyncio.run(chat_service.invoke_agent(query="hello", current_user=user))
    assert response == "123"

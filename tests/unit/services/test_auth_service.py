"""Unit tests for auth service business logic."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.db.models import TokenSession, UserRole
from app.services import auth_service
from tests.helpers import list_result, make_user, scalar_result


def test_login_for_access_token_success(mock_db, monkeypatch):
    user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1", username="alice")
    mock_db.execute.side_effect = [scalar_result(user)]

    monkeypatch.setattr(auth_service, "verify_password", lambda plain, hashed: True)
    monkeypatch.setattr(auth_service, "create_access_token", lambda data, expires_delta: "token-123")
    monkeypatch.setattr(auth_service, "rate_limit_exceeded", _async_return(False))

    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"})

    response = asyncio.run(
        auth_service.login_for_access_token(
            request=request,
            username="alice",
            password="pw",
            db=mock_db,
        )
    )

    assert response.access_token == "token-123"
    assert response.company_id == "c-1"
    assert mock_db.add.call_count == 1
    assert isinstance(mock_db.add.call_args.args[0], TokenSession)
    assert mock_db.commit.await_count == 1


def test_login_for_access_token_throttled_raises_429(mock_db, monkeypatch):
    monkeypatch.setattr(auth_service, "rate_limit_exceeded", _async_return(True))
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"), headers={"user-agent": "pytest"})

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_service.login_for_access_token(
                request=request,
                username="alice",
                password="pw",
                db=mock_db,
            )
        )

    assert exc_info.value.status_code == 429


def test_logout_unknown_session_raises_401(mock_db, monkeypatch):
    current_user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    monkeypatch.setattr(auth_service.jwt, "decode", lambda token, key, algorithms: {"jti": "j-1"})
    mock_db.execute.return_value = scalar_result(None)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(auth_service.logout(token="abc", current_user=current_user, db=mock_db))

    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Session not found"


def test_list_company_sessions_admin_cross_company_forbidden(mock_db):
    current_user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth_service.list_company_sessions(
                company_id="other-company",
                current_user=current_user,
                db=mock_db,
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Access denied"


def test_list_my_sessions_returns_list(mock_db):
    current_user = make_user(role=UserRole.ADMIN, company_id="c-1", user_id="u-1")
    session = TokenSession(
        user_id=current_user.id,
        jti="j1",
        expires_at=datetime.now(UTC),
    )
    mock_db.execute.return_value = list_result([session])

    sessions = asyncio.run(auth_service.list_my_sessions(current_user=current_user, db=mock_db))

    assert len(sessions) == 1
    assert sessions[0].jti == "j1"


def _async_return(value):
    async def _run(*_args, **_kwargs):
        return value

    return _run

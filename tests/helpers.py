"""Shared helper objects for tests."""

from app.db.models import User, UserRole


class ScalarResult:
    """Minimal scalar result adapter for mocked SQLAlchemy executes."""

    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class Scalars:
    """Minimal scalars adapter for mocked SQLAlchemy executes."""

    def __init__(self, values):
        self._values = values

    def all(self):
        return self._values


class ListResult:
    """Minimal result object exposing scalars().all() for list queries."""

    def __init__(self, values):
        self._values = values

    def scalars(self):
        return Scalars(self._values)


def scalar_result(value):
    """Create a scalar-style mocked execute result."""
    return ScalarResult(value)


def list_result(values):
    """Create a list-style mocked execute result."""
    return ListResult(values)


def make_user(*, role: UserRole, company_id: str | None = None, user_id: str = "u-1", username: str = "alice") -> User:
    """Create a lightweight ORM user instance for tests."""
    return User(id=user_id, username=username, hashed_password="hashed", role=role, company_id=company_id)

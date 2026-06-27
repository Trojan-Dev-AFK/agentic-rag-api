"""Lightweight lint to enforce thin endpoint modules.

Rule: endpoint files in app/api/v1/endpoints may only import transport-safe DB symbols:
- from sqlalchemy.ext.asyncio import AsyncSession
- from app.db.session import get_db
- from app.db.models import User

All other imports from sqlalchemy/app.db are rejected to keep business logic and
data access in app.services (and lower layers).
"""

from __future__ import annotations

import ast
from pathlib import Path

ENDPOINTS_DIR = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "endpoints"

_ALLOWED_IMPORTS: dict[str, set[str]] = {
    "sqlalchemy.ext.asyncio": {"AsyncSession"},
    "app.db.session": {"get_db"},
    "app.db.models": {"User"},
}

_RESTRICTED_PREFIXES = ("sqlalchemy", "app.db")


def _is_restricted(module: str) -> bool:
    return module.startswith(_RESTRICTED_PREFIXES)


def _import_violation(module: str, imported_names: set[str]) -> str | None:
    allowed_names = _ALLOWED_IMPORTS.get(module)
    if not _is_restricted(module):
        return None
    if allowed_names is None:
        return f"forbidden restricted import module '{module}'"
    extra_names = sorted(imported_names - allowed_names)
    if extra_names:
        return f"forbidden names {extra_names!r} imported from '{module}'"
    return None


def main() -> int:
    violations: list[str] = []

    for file_path in sorted(ENDPOINTS_DIR.glob("*.py")):
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    module = name.name
                    violation = _import_violation(module, set())
                    if violation:
                        line = getattr(node, "lineno", 1)
                        rel = file_path.relative_to(Path.cwd())
                        violations.append(f"{rel}:{line}: {violation}")
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imported_names = {name.name for name in node.names}
                violation = _import_violation(module, imported_names)
                if violation:
                    line = getattr(node, "lineno", 1)
                    rel = file_path.relative_to(Path.cwd())
                    violations.append(f"{rel}:{line}: {violation}")

    if violations:
        print("Thin endpoint lint failed:")
        for item in violations:
            print(item)
        return 1

    print("Thin endpoint lint passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

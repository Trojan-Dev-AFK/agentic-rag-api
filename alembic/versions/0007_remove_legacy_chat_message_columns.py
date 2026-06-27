"""remove legacy chat message columns

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("ALTER TABLE chat_messages DROP COLUMN IF EXISTS role"))
    op.execute(sa.text("ALTER TABLE chat_messages DROP COLUMN IF EXISTS content"))
    op.execute(sa.text("DROP TYPE IF EXISTS chatmessagerole"))


def downgrade() -> None:
    op.execute(sa.text("CREATE TYPE chatmessagerole AS ENUM ('user', 'assistant')"))
    op.execute(sa.text("""
        ALTER TABLE chat_messages
        ADD COLUMN IF NOT EXISTS role chatmessagerole,
        ADD COLUMN IF NOT EXISTS content TEXT
    """))
    op.execute(sa.text("""
        UPDATE chat_messages
        SET role = 'user', content = user_query
        WHERE content IS NULL
    """))

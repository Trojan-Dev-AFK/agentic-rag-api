"""chat messages single-turn rows

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE chat_messages
        ADD COLUMN IF NOT EXISTS user_query TEXT NOT NULL DEFAULT '',
        ADD COLUMN IF NOT EXISTS assistant_response TEXT NOT NULL DEFAULT ''
    """))

    # Backfill legacy two-row format into the new single-turn fields where possible.
    op.execute(sa.text("""
        UPDATE chat_messages
        SET user_query = content
        WHERE role::text = 'user' AND user_query = ''
    """))
    op.execute(sa.text("""
        UPDATE chat_messages
        SET assistant_response = content
        WHERE role::text = 'assistant' AND assistant_response = ''
    """))

    # Keep legacy columns for backward compatibility, but allow new writes without them.
    op.execute(sa.text("""
        ALTER TABLE chat_messages
        ALTER COLUMN role DROP NOT NULL,
        ALTER COLUMN content DROP NOT NULL
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE chat_messages
        ALTER COLUMN role SET NOT NULL,
        ALTER COLUMN content SET NOT NULL
    """))
    op.execute(sa.text("ALTER TABLE chat_messages DROP COLUMN IF EXISTS assistant_response"))
    op.execute(sa.text("ALTER TABLE chat_messages DROP COLUMN IF EXISTS user_query"))

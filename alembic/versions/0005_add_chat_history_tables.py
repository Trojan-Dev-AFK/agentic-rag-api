"""add chat history tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'chatmessagerole') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'chatmessagerole' AND e.enumlabel = 'assistant'
                ) THEN
                    DROP TYPE chatmessagerole CASCADE;
                    CREATE TYPE chatmessagerole AS ENUM ('user', 'assistant');
                END IF;
            ELSE
                CREATE TYPE chatmessagerole AS ENUM ('user', 'assistant');
            END IF;
        END $$
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id          VARCHAR      NOT NULL,
            user_id     VARCHAR      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            company_id  VARCHAR      NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
            title       VARCHAR,
            created_at  TIMESTAMPTZ  DEFAULT now(),
            updated_at  TIMESTAMPTZ  DEFAULT now(),
            PRIMARY KEY (id)
        )
    """))
    op.execute(sa.text("CREATE INDEX IF NOT EXISTS ix_chat_conversations_user_id ON chat_conversations (user_id)"))
    op.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_chat_conversations_company_id ON chat_conversations (company_id)")
    )

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id               VARCHAR          NOT NULL,
            conversation_id  VARCHAR          NOT NULL REFERENCES chat_conversations(id) ON DELETE CASCADE,
            role             chatmessagerole  NOT NULL,
            content          TEXT             NOT NULL,
            created_at       TIMESTAMPTZ      DEFAULT now(),
            PRIMARY KEY (id)
        )
    """))
    op.execute(
        sa.text("CREATE INDEX IF NOT EXISTS ix_chat_messages_conversation_id ON chat_messages (conversation_id)")
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS chat_messages"))
    op.execute(sa.text("DROP TABLE IF EXISTS chat_conversations"))
    op.execute(sa.text("DROP TYPE IF EXISTS chatmessagerole"))

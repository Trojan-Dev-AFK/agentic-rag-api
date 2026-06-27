"""add document chunk type

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'chunktype') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'chunktype' AND e.enumlabel = 'TABLE'
                ) THEN
                    DROP TYPE chunktype CASCADE;
                    CREATE TYPE chunktype AS ENUM ('TEXT', 'TABLE');
                END IF;
            ELSE
                CREATE TYPE chunktype AS ENUM ('TEXT', 'TABLE');
            END IF;
        END $$
    """))

    op.execute(sa.text("""
        ALTER TABLE document_chunks
        ADD COLUMN IF NOT EXISTS chunk_type chunktype NOT NULL DEFAULT 'TEXT'
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE document_chunks
        DROP COLUMN IF EXISTS chunk_type
    """))
    op.execute(sa.text("DROP TYPE IF EXISTS chunktype"))

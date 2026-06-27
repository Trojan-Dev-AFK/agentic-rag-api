"""add ocr chunk type

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-27
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(sa.text("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON t.oid = e.enumtypid
                WHERE t.typname = 'chunktype' AND e.enumlabel = 'OCR'
            ) THEN
                ALTER TYPE chunktype ADD VALUE 'OCR';
            END IF;
        END $$
    """))


def downgrade() -> None:
    # PostgreSQL does not support dropping enum values directly.
    # Downgrade is intentionally a no-op for enum label removal.
    pass

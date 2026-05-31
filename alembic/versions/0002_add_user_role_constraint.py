"""add super_admin company_id constraint

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-31
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enforce the invariant: super_admin users must never belong to a company.
    # Company admins and employees may have a NULL company_id only when their
    # parent company is deleted (ON DELETE SET NULL); that case is intentional
    # and is handled at the application layer, so we only constrain super_admin.
    op.execute(sa.text("""
        ALTER TABLE users
        ADD CONSTRAINT ck_users_super_admin_no_company
        CHECK (role != 'super_admin' OR company_id IS NULL)
    """))


def downgrade() -> None:
    op.execute(sa.text("""
        ALTER TABLE users
        DROP CONSTRAINT IF EXISTS ck_users_super_admin_no_company
    """))

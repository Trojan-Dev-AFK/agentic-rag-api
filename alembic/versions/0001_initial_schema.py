"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-05-31
"""

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Pure SQL throughout so SQLAlchemy's SchemaGenerator never fires.
    # op.create_table() triggers visit_enum() internally, which re-creates
    # enum types even with create_type=False, causing DuplicateObjectError
    # in the async asyncpg migration context.

    op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))

    # PostgreSQL has no CREATE TYPE IF NOT EXISTS.
    # The DO block checks whether the type exists AND has the expected values.
    # If the type exists but was created by an old schema (wrong labels), it is
    # dropped and recreated so the column DDL below succeeds.
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'userrole') THEN
                -- Verify the expected label 'super_admin' is present
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'userrole' AND e.enumlabel = 'super_admin'
                ) THEN
                    DROP TYPE userrole CASCADE;
                    CREATE TYPE userrole AS ENUM ('super_admin', 'admin', 'employee');
                END IF;
            ELSE
                CREATE TYPE userrole AS ENUM ('super_admin', 'admin', 'employee');
            END IF;
        END $$
    """))
    op.execute(sa.text("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = 'processingstatus') THEN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_enum e
                    JOIN pg_type t ON t.oid = e.enumtypid
                    WHERE t.typname = 'processingstatus' AND e.enumlabel = 'FAILED'
                ) THEN
                    DROP TYPE processingstatus CASCADE;
                    CREATE TYPE processingstatus AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED');
                END IF;
            ELSE
                CREATE TYPE processingstatus AS ENUM ('PENDING', 'PROCESSING', 'COMPLETED', 'FAILED');
            END IF;
        END $$
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS companies (
            id          VARCHAR      NOT NULL,
            name        VARCHAR      NOT NULL,
            industry    VARCHAR,
            description VARCHAR,
            created_at  TIMESTAMPTZ  DEFAULT now(),
            PRIMARY KEY (id)
        )
    """))
    op.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_companies_name ON companies (name)"))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS users (
            id              VARCHAR      NOT NULL,
            username        VARCHAR      NOT NULL,
            hashed_password VARCHAR      NOT NULL,
            role            userrole     NOT NULL DEFAULT 'employee',
            company_id      VARCHAR      REFERENCES companies(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ  DEFAULT now(),
            PRIMARY KEY (id)
        )
    """))
    op.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_username ON users (username)"))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS token_sessions (
            id          VARCHAR      NOT NULL,
            user_id     VARCHAR      NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            jti         VARCHAR      NOT NULL,
            issued_at   TIMESTAMPTZ  DEFAULT now(),
            expires_at  TIMESTAMPTZ  NOT NULL,
            revoked_at  TIMESTAMPTZ,
            logout_at   TIMESTAMPTZ,
            ip_address  VARCHAR,
            user_agent  VARCHAR,
            PRIMARY KEY (id)
        )
    """))
    op.execute(sa.text("CREATE UNIQUE INDEX IF NOT EXISTS ix_token_sessions_jti ON token_sessions (jti)"))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS documents (
            id          VARCHAR          NOT NULL,
            filename    VARCHAR          NOT NULL,
            status      processingstatus DEFAULT 'PENDING',
            company_id  VARCHAR          REFERENCES companies(id) ON DELETE CASCADE,
            created_at  TIMESTAMPTZ      DEFAULT now(),
            PRIMARY KEY (id)
        )
    """))

    op.execute(sa.text("""
        CREATE TABLE IF NOT EXISTS document_chunks (
            id           VARCHAR   NOT NULL,
            document_id  VARCHAR   REFERENCES documents(id) ON DELETE CASCADE,
            text_content VARCHAR   NOT NULL,
            embedding    vector(384),
            PRIMARY KEY (id)
        )
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TABLE IF EXISTS document_chunks"))
    op.execute(sa.text("DROP TABLE IF EXISTS documents"))
    op.execute(sa.text("DROP TABLE IF EXISTS token_sessions"))
    op.execute(sa.text("DROP TABLE IF EXISTS users"))
    op.execute(sa.text("DROP TABLE IF EXISTS companies"))
    op.execute(sa.text("DROP TYPE IF EXISTS processingstatus"))
    op.execute(sa.text("DROP TYPE IF EXISTS userrole"))
    op.execute(sa.text("DROP EXTENSION IF EXISTS vector"))

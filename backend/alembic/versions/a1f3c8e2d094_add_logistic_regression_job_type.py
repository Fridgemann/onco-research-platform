"""add logistic_regression to jobtype enum

Revision ID: a1f3c8e2d094
Revises: 0db05e37591c
Create Date: 2026-04-25

"""
from alembic import op

revision: str = 'a1f3c8e2d094'
down_revision: str = '0db05e37591c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ADD VALUE cannot run inside a transaction in PostgreSQL.
    # Committing first drops us out of the implicit transaction Alembic opens.
    op.execute("COMMIT")
    op.execute("ALTER TYPE jobtype ADD VALUE IF NOT EXISTS 'logistic_regression'")


def downgrade() -> None:
    # PostgreSQL has no ALTER TYPE DROP VALUE — removing an enum value
    # requires recreating the type, which is destructive. Leave as no-op.
    pass

"""add invite_revoked audit action

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-06
"""
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'invite_revoked'")


def downgrade() -> None:
    # PostgreSQL has no ALTER TYPE DROP VALUE — removing an enum value
    # requires recreating the type, which is destructive. Leave as no-op.
    pass

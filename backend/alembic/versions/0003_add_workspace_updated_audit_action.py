"""add workspace_updated audit action

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-30
"""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'workspace_updated'")


def downgrade() -> None:
    # Postgres does not support removing enum values; downgrade is a no-op.
    pass

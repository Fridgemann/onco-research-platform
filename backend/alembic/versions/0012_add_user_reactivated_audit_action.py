"""add user_reactivated audit action

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-06
"""
from alembic import op

revision: str = '0012'
down_revision: str = '0011'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'user_reactivated'")


def downgrade() -> None:
    pass

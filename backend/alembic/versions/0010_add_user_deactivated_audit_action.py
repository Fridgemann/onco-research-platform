"""add user_deactivated to auditaction enum

Revision ID: 0010_add_user_deactivated_audit_action
Revises: a1f3c8e2d094
Create Date: 2026-05-28

"""
from alembic import op

revision: str = '0010'
down_revision: str = '0009'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'user_deactivated'")


def downgrade() -> None:
    pass

"""add analysis_preflighted to auditaction enum

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-20

"""
from alembic import op

revision: str = '0013'
down_revision: str = '0012'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'analysis_preflighted'")


def downgrade() -> None:
    pass

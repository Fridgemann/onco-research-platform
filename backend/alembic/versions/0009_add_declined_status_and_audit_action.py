"""add declined invite status and audit action

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-10
"""
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE invitestatus ADD VALUE IF NOT EXISTS 'declined'")
    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'invite_declined'")


def downgrade() -> None:
    pass

"""add dataset_inspected to auditaction enum

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-03

"""
from alembic import op

revision: str = '0014'
down_revision: str = '0013'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Postgres cannot ALTER TYPE ... ADD VALUE inside a transaction block.
    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'dataset_inspected'")


def downgrade() -> None:
    # Postgres cannot cleanly drop an enum value; matches every prior
    # audit-action migration (0008-0013), which are all intentional no-ops.
    pass

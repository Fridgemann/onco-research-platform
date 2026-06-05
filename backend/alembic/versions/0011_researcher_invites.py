"""add researcher_invites table and audit actions

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-04
"""
from alembic import op
import sqlalchemy as sa

revision: str = '0011'
down_revision: str = '0010'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'researcher_invites',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('invited_email_encrypted', sa.String(512), nullable=False),
        sa.Column('invited_email_hash', sa.String(64), nullable=False, index=True),
        sa.Column('token_hash', sa.String(64), nullable=False, unique=True),
        sa.Column(
            'status',
            sa.Enum('pending', 'accepted', 'revoked', name='researcherinvitestatus'),
            nullable=False,
            server_default='pending',
        ),
        sa.Column('invited_by', sa.String(36), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    )

    op.execute("COMMIT")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'researcher_invited'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'researcher_invite_accepted'")
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'researcher_invite_revoked'")


def downgrade() -> None:
    op.drop_table('researcher_invites')

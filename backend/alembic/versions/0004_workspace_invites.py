"""workspace invites table and invite_accepted audit action

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create the workspace_invites table — let create_table handle the enum type creation
    op.create_table(
        "workspace_invites",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("invited_email_encrypted", sa.String(512), nullable=False),
        sa.Column("invited_email_hash", sa.String(64), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "revoked", name="invitestatus"),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("invited_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.create_index("ix_workspace_invites_workspace_id", "workspace_invites", ["workspace_id"])
    op.create_index("ix_workspace_invites_email_hash", "workspace_invites", ["invited_email_hash"])

    # Add invite_accepted to the auditaction enum
    op.execute("ALTER TYPE auditaction ADD VALUE IF NOT EXISTS 'invite_accepted'")


def downgrade() -> None:
    op.drop_table("workspace_invites")
    sa.Enum(name="invitestatus").drop(op.get_bind(), checkfirst=True)
    # Postgres does not support removing enum values; auditaction stays.

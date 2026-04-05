"""datasets table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-03
"""
from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id",
            sa.String(36),
            sa.ForeignKey("workspaces.id"),
            nullable=False,
        ),
        sa.Column(
            "uploaded_by",
            sa.String(36),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("filename_encrypted", sa.String(1024), nullable=False),
        sa.Column("filename_hash", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("object_key", sa.String(128), nullable=False, unique=True),
        sa.Column("description", sa.String(512), nullable=True),
        sa.Column(
            "status",
            sa.Enum("active", "deleted", name="datasetstatus"),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "is_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_datasets_workspace_id", "datasets", ["workspace_id"])
    op.create_index("ix_datasets_filename_hash", "datasets", ["filename_hash"])


def downgrade() -> None:
    op.drop_index("ix_datasets_filename_hash", table_name="datasets")
    op.drop_index("ix_datasets_workspace_id", table_name="datasets")
    op.drop_table("datasets")
    op.execute("DROP TYPE IF EXISTS datasetstatus;")

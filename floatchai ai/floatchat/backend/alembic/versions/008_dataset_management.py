"""
008 - Dataset Management

Feature 10: Adds admin audit logging and dataset lifecycle management fields.

Changes:
    - Create admin_audit_log table
    - Add description, is_public, tags, deleted_at, deleted_by to datasets
    - Add source to ingestion_jobs

Revision ID: 008
Revises: 007
Create Date: 2026-03-08
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


# Revision identifiers
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply Feature 10 schema changes."""

    # =========================================================================
    # Step 1: Create admin_audit_log table
    # =========================================================================
    op.create_table(
        "admin_audit_log",
        sa.Column(
            "log_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("admin_user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(50), nullable=False),
        sa.Column("entity_id", sa.String(100), nullable=False),
        sa.Column("details", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.user_id"],
            name="fk_admin_audit_log_admin_user_id",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "action IN ('dataset_upload_started', 'dataset_soft_deleted', 'dataset_hard_deleted', "
            "'dataset_metadata_updated', 'dataset_summary_regenerated', 'dataset_visibility_changed', "
            "'ingestion_job_retried', 'hard_delete_requested', 'hard_delete_completed')",
            name="ck_admin_audit_log_action",
        ),
        sa.CheckConstraint(
            "entity_type IN ('dataset', 'ingestion_job')",
            name="ck_admin_audit_log_entity_type",
        ),
    )

    op.create_index(
        "ix_admin_audit_log_admin_user_id",
        "admin_audit_log",
        ["admin_user_id"],
    )
    op.create_index(
        "ix_admin_audit_log_created_at",
        "admin_audit_log",
        ["created_at"],
    )
    op.create_index(
        "ix_admin_audit_log_entity_type_entity_id",
        "admin_audit_log",
        ["entity_type", "entity_id"],
    )

    # =========================================================================
    # Step 2: Add columns to datasets
    # =========================================================================
    op.add_column("datasets", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "datasets",
        sa.Column(
            "is_public",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column("datasets", sa.Column("tags", JSONB, nullable=True))
    op.add_column(
        "datasets",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "datasets",
        sa.Column("deleted_by", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_datasets_deleted_by",
        "datasets",
        "users",
        ["deleted_by"],
        ["user_id"],
        ondelete="SET NULL",
    )

    # =========================================================================
    # Step 3: Add source column to ingestion_jobs
    # =========================================================================
    op.add_column(
        "ingestion_jobs",
        sa.Column(
            "source",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'manual_upload'"),
        ),
    )
    op.create_check_constraint(
        "ck_ingestion_jobs_source",
        "ingestion_jobs",
        "source IN ('manual_upload', 'gdac_sync')",
    )


def downgrade() -> None:
    """Reverse Feature 10 schema changes."""

    # =========================================================================
    # Step 1: Remove ingestion_jobs additions
    # =========================================================================
    op.drop_constraint("ck_ingestion_jobs_source", "ingestion_jobs", type_="check")
    op.drop_column("ingestion_jobs", "source")

    # =========================================================================
    # Step 2: Remove datasets additions
    # =========================================================================
    op.drop_constraint("fk_datasets_deleted_by", "datasets", type_="foreignkey")
    op.drop_column("datasets", "deleted_by")
    op.drop_column("datasets", "deleted_at")
    op.drop_column("datasets", "tags")
    op.drop_column("datasets", "is_public")
    op.drop_column("datasets", "description")

    # =========================================================================
    # Step 3: Drop admin_audit_log table and indexes
    # =========================================================================
    op.drop_index("ix_admin_audit_log_entity_type_entity_id", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_created_at", table_name="admin_audit_log")
    op.drop_index("ix_admin_audit_log_admin_user_id", table_name="admin_audit_log")
    op.drop_table("admin_audit_log")

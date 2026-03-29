"""
009 - API Layer

Feature 11: Adds API key storage for public API authentication.

Changes:
    - Create api_keys table
    - Extend admin_audit_log check constraints for API key actions

Revision ID: 009
Revises: 010
Create Date: 2026-03-26
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Revision identifiers
revision = "009"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply Feature 11 schema changes."""

    op.create_table(
        "api_keys",
        sa.Column(
            "key_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("key_hash", sa.String(64), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rate_limit_override", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.user_id"],
            name="fk_api_keys_user_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"])

    op.drop_constraint("ck_admin_audit_log_action", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_action",
        "admin_audit_log",
        "action IN ('dataset_upload_started', 'dataset_soft_deleted', 'dataset_hard_deleted', "
        "'dataset_metadata_updated', 'dataset_summary_regenerated', 'dataset_visibility_changed', "
        "'ingestion_job_retried', 'hard_delete_requested', 'hard_delete_completed', "
        "'gdac_sync_triggered', 'api_key_created', 'api_key_revoked', 'api_key_updated')",
    )

    op.drop_constraint("ck_admin_audit_log_entity_type", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_entity_type",
        "admin_audit_log",
        "entity_type IN ('dataset', 'ingestion_job', 'gdac_sync_run', 'api_key')",
    )


def downgrade() -> None:
    """Reverse Feature 11 schema changes."""

    op.drop_constraint("ck_admin_audit_log_entity_type", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_entity_type",
        "admin_audit_log",
        "entity_type IN ('dataset', 'ingestion_job', 'gdac_sync_run')",
    )

    op.drop_constraint("ck_admin_audit_log_action", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_action",
        "admin_audit_log",
        "action IN ('dataset_upload_started', 'dataset_soft_deleted', 'dataset_hard_deleted', "
        "'dataset_metadata_updated', 'dataset_summary_regenerated', 'dataset_visibility_changed', "
        "'ingestion_job_retried', 'hard_delete_requested', 'hard_delete_completed', "
        "'gdac_sync_triggered')",
    )

    op.drop_index("ix_api_keys_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_table("api_keys")

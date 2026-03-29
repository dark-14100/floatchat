"""
010 - GDAC Auto-Sync

Creates tables for GDAC synchronization run history and checkpoint state.
Also updates admin audit log constraints for GDAC sync actions.

Revision ID: 010
Revises: 008
Create Date: 2026-03-09
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Revision identifiers
revision = "010"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply GDAC Auto-Sync schema changes."""

    # =========================================================================
    # Step 1: Create gdac_sync_runs table
    # =========================================================================
    op.create_table(
        "gdac_sync_runs",
        sa.Column(
            "run_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("index_profiles_found", sa.Integer(), nullable=True),
        sa.Column("profiles_downloaded", sa.Integer(), nullable=True),
        sa.Column("profiles_ingested", sa.Integer(), nullable=True),
        sa.Column("profiles_skipped", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("gdac_mirror", sa.String(100), nullable=False),
        sa.Column("lookback_days", sa.Integer(), nullable=False),
        sa.Column("triggered_by", sa.String(20), nullable=False),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'partial')",
            name="ck_gdac_sync_runs_status",
        ),
        sa.CheckConstraint(
            "triggered_by IN ('scheduled', 'manual')",
            name="ck_gdac_sync_runs_triggered_by",
        ),
    )

    op.create_index(
        "ix_gdac_sync_runs_started_at",
        "gdac_sync_runs",
        ["started_at"],
    )
    op.create_index(
        "ix_gdac_sync_runs_status",
        "gdac_sync_runs",
        ["status"],
    )

    # =========================================================================
    # Step 2: Create gdac_sync_state table and seed keys
    # =========================================================================
    op.create_table(
        "gdac_sync_state",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.execute(
        """
        INSERT INTO gdac_sync_state (key, value)
        VALUES
            ('last_sync_index_date', ''),
            ('last_sync_completed_at', '')
        """
    )

    # =========================================================================
    # Step 3: Grant readonly access to gdac_sync_runs (conditional)
    # =========================================================================
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'floatchat_readonly'
            ) THEN
                GRANT SELECT ON TABLE gdac_sync_runs TO floatchat_readonly;
            END IF;
        END
        $$;
        """
    )

    # =========================================================================
    # Step 4: Update admin_audit_log check constraints for GDAC actions
    # =========================================================================
    op.drop_constraint("ck_admin_audit_log_action", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_action",
        "admin_audit_log",
        "action IN ('dataset_upload_started', 'dataset_soft_deleted', 'dataset_hard_deleted', "
        "'dataset_metadata_updated', 'dataset_summary_regenerated', 'dataset_visibility_changed', "
        "'ingestion_job_retried', 'hard_delete_requested', 'hard_delete_completed', "
        "'gdac_sync_triggered')",
    )

    op.drop_constraint("ck_admin_audit_log_entity_type", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_entity_type",
        "admin_audit_log",
        "entity_type IN ('dataset', 'ingestion_job', 'gdac_sync_run')",
    )


def downgrade() -> None:
    """Reverse GDAC Auto-Sync schema changes."""

    # =========================================================================
    # Step 1: Restore admin_audit_log check constraints to pre-GDAC values
    # =========================================================================
    op.drop_constraint("ck_admin_audit_log_entity_type", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_entity_type",
        "admin_audit_log",
        "entity_type IN ('dataset', 'ingestion_job')",
    )

    op.drop_constraint("ck_admin_audit_log_action", "admin_audit_log", type_="check")
    op.create_check_constraint(
        "ck_admin_audit_log_action",
        "admin_audit_log",
        "action IN ('dataset_upload_started', 'dataset_soft_deleted', 'dataset_hard_deleted', "
        "'dataset_metadata_updated', 'dataset_summary_regenerated', 'dataset_visibility_changed', "
        "'ingestion_job_retried', 'hard_delete_requested', 'hard_delete_completed')",
    )

    # =========================================================================
    # Step 2: Drop GDAC tables and indexes
    # =========================================================================
    op.drop_table("gdac_sync_state")
    op.drop_index("ix_gdac_sync_runs_status", table_name="gdac_sync_runs")
    op.drop_index("ix_gdac_sync_runs_started_at", table_name="gdac_sync_runs")
    op.drop_table("gdac_sync_runs")

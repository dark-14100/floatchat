"""
007 - Anomaly Detection

Feature 15: Adds anomalies and anomaly_baselines tables.

New tables:
    - anomalies
    - anomaly_baselines

Indexes:
    - B-tree index on anomalies.detected_at
    - B-tree index on anomalies.float_id
    - Composite B-tree index on anomalies(is_reviewed, detected_at)
    - B-tree index on anomalies.severity
    - B-tree index on anomaly_baselines(region, variable, month)

Revision ID: 007
Revises: 006
Create Date: 2026-03-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# Revision identifiers
revision = "007"
down_revision = "006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create anomalies and anomaly_baselines tables with indexes."""

    # =========================================================================
    # Step 1: Create anomalies table
    # =========================================================================
    op.create_table(
        "anomalies",
        sa.Column(
            "anomaly_id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("float_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.BigInteger(), nullable=False),
        sa.Column("anomaly_type", sa.String(50), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("variable", sa.String(50), nullable=False),
        sa.Column("baseline_value", sa.Float(), nullable=True),
        sa.Column("observed_value", sa.Float(), nullable=True),
        sa.Column("deviation_percent", sa.Float(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "detected_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column(
            "is_reviewed",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("reviewed_by", UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["float_id"],
            ["floats.float_id"],
            name="fk_anomalies_float_id",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profiles.profile_id"],
            name="fk_anomalies_profile_id",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"],
            ["users.user_id"],
            name="fk_anomalies_reviewed_by",
            ondelete="SET NULL",
        ),
        sa.CheckConstraint(
            "anomaly_type IN ('spatial_baseline', 'float_self_comparison', 'cluster_pattern', 'seasonal_baseline')",
            name="ck_anomalies_anomaly_type",
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_anomalies_severity",
        ),
    )

    # Required indexes from PRD
    op.create_index("ix_anomalies_detected_at", "anomalies", ["detected_at"])
    op.create_index("ix_anomalies_float_id", "anomalies", ["float_id"])
    op.create_index(
        "ix_anomalies_is_reviewed_detected_at",
        "anomalies",
        ["is_reviewed", "detected_at"],
    )
    op.create_index("ix_anomalies_severity", "anomalies", ["severity"])

    # =========================================================================
    # Step 2: Create anomaly_baselines table
    # =========================================================================
    op.create_table(
        "anomaly_baselines",
        sa.Column("baseline_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("variable", sa.String(50), nullable=False),
        sa.Column("month", sa.Integer(), nullable=False),
        sa.Column("mean_value", sa.Float(), nullable=False),
        sa.Column("std_dev", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("baseline_id"),
        sa.UniqueConstraint(
            "region",
            "variable",
            "month",
            name="uq_anomaly_baselines_region_variable_month",
        ),
        sa.CheckConstraint("month BETWEEN 1 AND 12", name="ck_anomaly_baselines_month"),
    )

    op.create_index(
        "ix_anomaly_baselines_region_variable_month",
        "anomaly_baselines",
        ["region", "variable", "month"],
    )

    # =========================================================================
    # Step 3: Explicit readonly grants for new tables
    # =========================================================================
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'floatchat_readonly'
            ) THEN
                GRANT SELECT ON TABLE anomalies TO floatchat_readonly;
                GRANT SELECT ON TABLE anomaly_baselines TO floatchat_readonly;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    """Drop anomaly tables and indexes."""

    op.drop_index(
        "ix_anomaly_baselines_region_variable_month",
        table_name="anomaly_baselines",
    )
    op.drop_table("anomaly_baselines")

    op.drop_index("ix_anomalies_severity", table_name="anomalies")
    op.drop_index("ix_anomalies_is_reviewed_detected_at", table_name="anomalies")
    op.drop_index("ix_anomalies_float_id", table_name="anomalies")
    op.drop_index("ix_anomalies_detected_at", table_name="anomalies")
    op.drop_table("anomalies")

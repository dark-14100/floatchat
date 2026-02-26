"""
002 - Ocean Database

Feature 2: Extends the initial schema with spatial indexes, new tables,
materialized views, BIGINT corrections, and a read-only database user.

Changes:
    - Enable pg_trgm and postgis_topology extensions
    - ALTER profiles.profile_id, measurements.measurement_id,
      measurements.profile_id from INTEGER to BIGINT (BIGSERIAL correction)
    - Create ocean_regions table (named ocean basin polygons)
    - Create dataset_versions table (audit log for re-ingestion)
    - Add missing indexes on profiles, datasets, floats
    - Create mv_float_latest_position materialized view
    - Create mv_dataset_stats materialized view
    - Create floatchat_readonly PostgreSQL user with SELECT-only

Revision ID: 002
Revises: 001
Create Date: 2026-02-26
"""

import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers
revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Apply Feature 2 schema changes."""

    # =========================================================================
    # Step 1: Enable additional PostgreSQL extensions
    # (postgis and pgcrypto already enabled in 001 — do NOT re-enable)
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis_topology")

    # =========================================================================
    # Step 2: ALTER columns from INTEGER to BIGINT (BIGSERIAL correction)
    # profiles.profile_id, measurements.measurement_id, measurements.profile_id
    # =========================================================================

    # Drop the FK constraint on measurements.profile_id before altering types
    op.drop_constraint("fk_measurements_profile_id", "measurements", type_="foreignkey")

    # ALTER profiles.profile_id to BIGINT
    op.execute("ALTER TABLE profiles ALTER COLUMN profile_id TYPE BIGINT")

    # ALTER measurements.measurement_id to BIGINT
    op.execute("ALTER TABLE measurements ALTER COLUMN measurement_id TYPE BIGINT")

    # ALTER measurements.profile_id (FK column) to BIGINT
    op.execute("ALTER TABLE measurements ALTER COLUMN profile_id TYPE BIGINT")

    # Re-create the FK constraint after altering types
    op.create_foreign_key(
        "fk_measurements_profile_id",
        "measurements",
        "profiles",
        ["profile_id"],
        ["profile_id"],
        ondelete="CASCADE",
    )

    # =========================================================================
    # Step 3: Create ocean_regions table
    # =========================================================================
    op.create_table(
        "ocean_regions",
        sa.Column("region_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("region_name", sa.String(255), nullable=False),
        sa.Column("region_type", sa.String(50), nullable=True),
        sa.Column("parent_region_id", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("region_id"),
        sa.UniqueConstraint("region_name", name="uq_ocean_regions_region_name"),
        sa.ForeignKeyConstraint(
            ["parent_region_id"],
            ["ocean_regions.region_id"],
            name="fk_ocean_regions_parent",
        ),
        sa.CheckConstraint(
            "region_type IN ('ocean', 'sea', 'bay', 'gulf')",
            name="ck_ocean_regions_region_type",
        ),
    )

    # Add PostGIS GEOGRAPHY POLYGON column
    op.execute("""
        ALTER TABLE ocean_regions
        ADD COLUMN geom GEOGRAPHY(POLYGON, 4326)
    """)

    # GiST index on ocean_regions.geom
    op.execute("""
        CREATE INDEX idx_ocean_regions_geom
        ON ocean_regions USING GIST (geom)
    """)

    # =========================================================================
    # Step 4: Create dataset_versions table
    # =========================================================================
    op.create_table(
        "dataset_versions",
        sa.Column("version_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("dataset_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("ingestion_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("profile_count", sa.Integer(), nullable=True),
        sa.Column("float_count", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("version_id"),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.dataset_id"],
            name="fk_dataset_versions_dataset_id",
        ),
    )

    # =========================================================================
    # Step 5: Add missing indexes to tables created in migration 001
    # =========================================================================

    # --- profiles ---
    # Composite B-tree on (float_id, timestamp) — for float time series queries
    op.create_index(
        "idx_profiles_float_id_timestamp",
        "profiles",
        ["float_id", "timestamp"],
    )

    # Partial index on profiles where position_invalid = FALSE
    # (spatial queries only care about valid positions)
    op.execute("""
        CREATE INDEX idx_profiles_valid_position
        ON profiles (profile_id)
        WHERE position_invalid = FALSE
    """)

    # Partial index on profiles.timestamp where timestamp_missing = FALSE
    # (time queries only care about profiles with timestamps)
    op.execute("""
        CREATE INDEX idx_profiles_valid_timestamp
        ON profiles (timestamp)
        WHERE timestamp_missing = FALSE
    """)

    # --- datasets ---
    # GiST index on datasets.bbox
    op.execute("""
        CREATE INDEX idx_datasets_bbox
        ON datasets USING GIST (bbox)
    """)

    # Partial index on datasets where is_active = TRUE
    op.execute("""
        CREATE INDEX idx_datasets_active
        ON datasets (dataset_id)
        WHERE is_active = TRUE
    """)

    # --- floats ---
    # B-tree index on floats.float_type
    op.create_index("idx_floats_float_type", "floats", ["float_type"])

    # =========================================================================
    # Step 6: Create materialized views
    # =========================================================================

    # mv_float_latest_position — latest position per float
    op.execute("""
        CREATE MATERIALIZED VIEW mv_float_latest_position AS
        SELECT DISTINCT ON (f.platform_number)
            f.platform_number,
            f.float_id,
            p.cycle_number,
            p.timestamp,
            p.latitude,
            p.longitude,
            p.geom
        FROM profiles p
        JOIN floats f ON f.float_id = p.float_id
        WHERE p.position_invalid = FALSE
        ORDER BY f.platform_number, p.cycle_number DESC
        WITH NO DATA
    """)

    # GiST index on the materialized view's geom column
    op.execute("""
        CREATE INDEX idx_mv_float_latest_position_geom
        ON mv_float_latest_position USING GIST (geom)
    """)

    # mv_dataset_stats — per-dataset aggregated stats
    op.execute("""
        CREATE MATERIALIZED VIEW mv_dataset_stats AS
        SELECT
            d.dataset_id,
            d.name,
            COUNT(DISTINCT p.profile_id) AS profile_count,
            COUNT(DISTINCT p.float_id) AS float_count,
            MIN(p.timestamp) AS date_range_start,
            MAX(p.timestamp) AS date_range_end
        FROM datasets d
        LEFT JOIN profiles p ON p.dataset_id = d.dataset_id
        WHERE d.is_active = TRUE
        GROUP BY d.dataset_id, d.name
        WITH NO DATA
    """)

    # =========================================================================
    # Step 7: Create floatchat_readonly PostgreSQL user
    # =========================================================================
    readonly_password = os.environ.get("READONLY_DB_PASSWORD", "floatchat_readonly")

    # Create user (idempotent via DO block)
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'floatchat_readonly'
            ) THEN
                CREATE ROLE floatchat_readonly WITH LOGIN PASSWORD '{readonly_password}';
            END IF;
        END
        $$;
    """)

    # Grant SELECT on all existing tables
    op.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO floatchat_readonly")

    # Grant SELECT on materialized views (covered by above GRANT ALL TABLES,
    # but explicit for clarity)
    op.execute("GRANT SELECT ON mv_float_latest_position TO floatchat_readonly")
    op.execute("GRANT SELECT ON mv_dataset_stats TO floatchat_readonly")

    # Grant USAGE on the public schema so the user can access it
    op.execute("GRANT USAGE ON SCHEMA public TO floatchat_readonly")


def downgrade() -> None:
    """Reverse all Feature 2 schema changes."""

    # =========================================================================
    # Drop materialized views first
    # =========================================================================
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_dataset_stats")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_float_latest_position")

    # =========================================================================
    # Drop Feature 2 indexes on existing tables
    # =========================================================================
    op.execute("DROP INDEX IF EXISTS idx_floats_float_type")
    op.execute("DROP INDEX IF EXISTS idx_datasets_active")
    op.execute("DROP INDEX IF EXISTS idx_datasets_bbox")
    op.execute("DROP INDEX IF EXISTS idx_profiles_valid_timestamp")
    op.execute("DROP INDEX IF EXISTS idx_profiles_valid_position")
    op.execute("DROP INDEX IF EXISTS idx_profiles_float_id_timestamp")

    # =========================================================================
    # Drop Feature 2 tables
    # =========================================================================
    op.drop_table("dataset_versions")
    op.drop_table("ocean_regions")

    # =========================================================================
    # Revert BIGINT columns back to INTEGER
    # =========================================================================
    op.drop_constraint("fk_measurements_profile_id", "measurements", type_="foreignkey")
    op.execute("ALTER TABLE measurements ALTER COLUMN profile_id TYPE INTEGER")
    op.execute("ALTER TABLE measurements ALTER COLUMN measurement_id TYPE INTEGER")
    op.execute("ALTER TABLE profiles ALTER COLUMN profile_id TYPE INTEGER")
    op.create_foreign_key(
        "fk_measurements_profile_id",
        "measurements",
        "profiles",
        ["profile_id"],
        ["profile_id"],
        ondelete="CASCADE",
    )

    # =========================================================================
    # Revoke privileges and drop the readonly user
    # =========================================================================
    op.execute("REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM floatchat_readonly")
    op.execute("REVOKE USAGE ON SCHEMA public FROM floatchat_readonly")
    op.execute("""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = 'floatchat_readonly'
            ) THEN
                DROP ROLE floatchat_readonly;
            END IF;
        END
        $$;
    """)

    # =========================================================================
    # Drop extensions added in this migration
    # =========================================================================
    op.execute("DROP EXTENSION IF EXISTS postgis_topology")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")

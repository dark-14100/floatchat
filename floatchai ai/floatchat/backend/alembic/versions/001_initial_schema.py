"""
001 - Initial Schema

Create all 6 tables for the FloatChat Data Ingestion Pipeline.

IMPORTANT: Tables are created in FK-dependency order:
    1. floats
    2. datasets
    3. profiles (FK → floats, datasets)
    4. measurements (FK → profiles)
    5. float_positions
    6. ingestion_jobs (FK → datasets)

PostGIS geometry columns are added via raw SQL after table creation.
This migration is hand-written - do NOT use Alembic autogenerate.

Revision ID: 001
Revises: None
Create Date: 2026-02-25
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Revision identifiers
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables and indexes."""
    
    # =========================================================================
    # Enable PostgreSQL Extensions
    # =========================================================================
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    
    # =========================================================================
    # Table 1: floats
    # =========================================================================
    op.create_table(
        "floats",
        sa.Column("float_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_number", sa.String(20), nullable=False),
        sa.Column("wmo_id", sa.String(20), nullable=True),
        sa.Column("float_type", sa.String(10), nullable=True),
        sa.Column("deployment_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deployment_lat", sa.Double(), nullable=True),
        sa.Column("deployment_lon", sa.Double(), nullable=True),
        sa.Column("country", sa.String(100), nullable=True),
        sa.Column("program", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("float_id"),
        sa.UniqueConstraint("platform_number", name="uq_floats_platform_number"),
        sa.CheckConstraint("float_type IN ('core', 'BGC', 'deep')", name="ck_floats_float_type"),
    )
    
    # =========================================================================
    # Table 2: datasets
    # =========================================================================
    op.create_table(
        "datasets",
        sa.Column("dataset_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("source_filename", sa.String(500), nullable=True),
        sa.Column("raw_file_path", sa.String(1000), nullable=True),
        sa.Column("ingestion_date", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("date_range_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("date_range_end", sa.DateTime(timezone=True), nullable=True),
        # bbox geography column added below via raw SQL
        sa.Column("float_count", sa.Integer(), nullable=True),
        sa.Column("profile_count", sa.Integer(), nullable=True),
        sa.Column("variable_list", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("summary_text", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("dataset_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("dataset_id"),
    )
    
    # Add PostGIS GEOGRAPHY POLYGON column for bounding box
    op.execute("""
        ALTER TABLE datasets 
        ADD COLUMN bbox GEOGRAPHY(POLYGON, 4326)
    """)
    
    # =========================================================================
    # Table 3: profiles
    # =========================================================================
    op.create_table(
        "profiles",
        sa.Column("profile_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("float_id", sa.Integer(), nullable=False),
        sa.Column("platform_number", sa.String(20), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("juld_raw", sa.Double(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timestamp_missing", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        sa.Column("position_invalid", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        # geom geography column added below via raw SQL
        sa.Column("data_mode", sa.String(1), nullable=True),
        sa.Column("dataset_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("profile_id"),
        sa.ForeignKeyConstraint(["float_id"], ["floats.float_id"], name="fk_profiles_float_id"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.dataset_id"], name="fk_profiles_dataset_id"),
        sa.UniqueConstraint("platform_number", "cycle_number", name="uq_profiles_platform_cycle"),
        sa.CheckConstraint("data_mode IN ('R', 'A', 'D')", name="ck_profiles_data_mode"),
    )
    
    # Add PostGIS GEOGRAPHY POINT column for geometry
    op.execute("""
        ALTER TABLE profiles 
        ADD COLUMN geom GEOGRAPHY(POINT, 4326)
    """)
    
    # Create indexes for profiles
    op.create_index("idx_profiles_float_id", "profiles", ["float_id"])
    op.create_index("idx_profiles_dataset_id", "profiles", ["dataset_id"])
    
    # GiST index on geometry column for spatial queries
    op.execute("""
        CREATE INDEX idx_profiles_geom ON profiles USING GIST (geom)
    """)
    
    # BRIN index on timestamp for time-range queries (efficient for sequential data)
    op.execute("""
        CREATE INDEX idx_profiles_timestamp ON profiles USING BRIN (timestamp)
    """)
    
    # =========================================================================
    # Table 4: measurements
    # =========================================================================
    op.create_table(
        "measurements",
        sa.Column("measurement_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        # Core oceanographic variables
        sa.Column("pressure", sa.Double(), nullable=True),
        sa.Column("temperature", sa.Double(), nullable=True),
        sa.Column("salinity", sa.Double(), nullable=True),
        # BGC variables (optional)
        sa.Column("dissolved_oxygen", sa.Double(), nullable=True),
        sa.Column("chlorophyll", sa.Double(), nullable=True),
        sa.Column("nitrate", sa.Double(), nullable=True),
        sa.Column("ph", sa.Double(), nullable=True),
        sa.Column("bbp700", sa.Double(), nullable=True),
        sa.Column("downwelling_irradiance", sa.Double(), nullable=True),
        # QC flags
        sa.Column("pres_qc", sa.SmallInteger(), nullable=True),
        sa.Column("temp_qc", sa.SmallInteger(), nullable=True),
        sa.Column("psal_qc", sa.SmallInteger(), nullable=True),
        sa.Column("doxy_qc", sa.SmallInteger(), nullable=True),
        sa.Column("chla_qc", sa.SmallInteger(), nullable=True),
        sa.Column("nitrate_qc", sa.SmallInteger(), nullable=True),
        sa.Column("ph_qc", sa.SmallInteger(), nullable=True),
        # Outlier flag
        sa.Column("is_outlier", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.PrimaryKeyConstraint("measurement_id"),
        sa.ForeignKeyConstraint(
            ["profile_id"], 
            ["profiles.profile_id"], 
            name="fk_measurements_profile_id",
            ondelete="CASCADE"
        ),
    )
    
    # Create indexes for measurements
    op.create_index("idx_measurements_profile_id", "measurements", ["profile_id"])
    op.create_index("idx_measurements_pressure", "measurements", ["pressure"])
    
    # =========================================================================
    # Table 5: float_positions
    # =========================================================================
    op.create_table(
        "float_positions",
        sa.Column("position_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("platform_number", sa.String(20), nullable=False),
        sa.Column("cycle_number", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latitude", sa.Double(), nullable=True),
        sa.Column("longitude", sa.Double(), nullable=True),
        # geom geography column added below via raw SQL
        sa.PrimaryKeyConstraint("position_id"),
        sa.UniqueConstraint("platform_number", "cycle_number", name="uq_float_positions_platform_cycle"),
    )
    
    # Add PostGIS GEOGRAPHY POINT column for geometry
    op.execute("""
        ALTER TABLE float_positions 
        ADD COLUMN geom GEOGRAPHY(POINT, 4326)
    """)
    
    # GiST index on geometry column for spatial queries
    op.execute("""
        CREATE INDEX idx_float_positions_geom ON float_positions USING GIST (geom)
    """)
    
    # =========================================================================
    # Table 6: ingestion_jobs
    # =========================================================================
    op.create_table(
        "ingestion_jobs",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("dataset_id", sa.Integer(), nullable=True),
        sa.Column("original_filename", sa.String(500), nullable=True),
        sa.Column("raw_file_path", sa.String(1000), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("progress_pct", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("profiles_total", sa.Integer(), nullable=True),
        sa.Column("profiles_ingested", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("errors", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'[]'")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
        sa.ForeignKeyConstraint(["dataset_id"], ["datasets.dataset_id"], name="fk_ingestion_jobs_dataset_id"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')", 
            name="ck_ingestion_jobs_status"
        ),
    )
    
    # Create index for status filtering
    op.create_index("idx_ingestion_jobs_status", "ingestion_jobs", ["status"])
    op.create_index("idx_ingestion_jobs_dataset_id", "ingestion_jobs", ["dataset_id"])


def downgrade() -> None:
    """Drop all tables in reverse FK-dependency order."""
    
    # Drop tables in reverse order
    op.drop_table("ingestion_jobs")
    op.drop_table("float_positions")
    op.drop_table("measurements")
    op.drop_table("profiles")
    op.drop_table("datasets")
    op.drop_table("floats")
    
    # Note: We don't drop the PostGIS/pgcrypto extensions as they may be used by other schemas

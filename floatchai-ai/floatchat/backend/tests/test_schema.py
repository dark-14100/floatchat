"""
Feature 2 — Schema verification tests.

Confirms that all tables, indexes, constraints, materialized views, and
BIGINT column corrections are present in PostgreSQL after running
migrations 001 + 002.

Requires:
    - Docker PostgreSQL+PostGIS running on port 5432
    - ``alembic upgrade head`` completed
"""

import pytest
from sqlalchemy import text


# ============================================================================
# Table existence (8 tables total)
# ============================================================================
EXPECTED_TABLES = [
    "floats",
    "datasets",
    "profiles",
    "measurements",
    "float_positions",
    "ingestion_jobs",
    "ocean_regions",
    "dataset_versions",
]


@pytest.mark.parametrize("table_name", EXPECTED_TABLES)
def test_table_exists(pg_session, table_name):
    """All 8 tables must exist in the public schema."""
    exists = pg_session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM pg_tables"
            "  WHERE schemaname = 'public' AND tablename = :name"
            ")"
        ),
        {"name": table_name},
    ).scalar()
    assert exists, f"Table '{table_name}' not found"


# ============================================================================
# GiST spatial indexes
# ============================================================================
EXPECTED_GIST_INDEXES = [
    "idx_profiles_geom",
    "idx_float_positions_geom",
    "idx_ocean_regions_geom",
    "idx_datasets_bbox",
    "idx_mv_float_latest_position_geom",
]


@pytest.mark.parametrize("index_name", EXPECTED_GIST_INDEXES)
def test_gist_index_exists(pg_session, index_name):
    """All GiST spatial indexes must be present."""
    exists = pg_session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"),
        {"name": index_name},
    ).scalar()
    assert exists, f"GiST index '{index_name}' not found"


# ============================================================================
# BRIN index on profiles.timestamp
# ============================================================================
def test_brin_index_on_profiles_timestamp(pg_session):
    """A BRIN index must exist on profiles.timestamp for time-range queries."""
    row = pg_session.execute(
        text(
            "SELECT indexdef FROM pg_indexes"
            " WHERE indexname = 'idx_profiles_timestamp'"
        )
    ).scalar()
    assert row is not None, "idx_profiles_timestamp not found"
    assert "brin" in row.lower(), "idx_profiles_timestamp is not a BRIN index"


# ============================================================================
# B-tree / composite indexes
# ============================================================================
EXPECTED_BTREE_INDEXES = [
    "idx_profiles_float_id",
    "idx_profiles_dataset_id",
    "idx_profiles_float_id_timestamp",
    "idx_measurements_profile_id",
    "idx_measurements_pressure",
    "idx_floats_float_type",
]


@pytest.mark.parametrize("index_name", EXPECTED_BTREE_INDEXES)
def test_btree_index_exists(pg_session, index_name):
    """B-tree indexes must exist for join and filter performance."""
    exists = pg_session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"),
        {"name": index_name},
    ).scalar()
    assert exists, f"B-tree index '{index_name}' not found"


# ============================================================================
# Partial indexes
# ============================================================================
EXPECTED_PARTIAL_INDEXES = [
    "idx_profiles_valid_position",
    "idx_profiles_valid_timestamp",
    "idx_datasets_active",
]


@pytest.mark.parametrize("index_name", EXPECTED_PARTIAL_INDEXES)
def test_partial_index_exists(pg_session, index_name):
    """Partial indexes must exist for filtered queries."""
    exists = pg_session.execute(
        text("SELECT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname = :name)"),
        {"name": index_name},
    ).scalar()
    assert exists, f"Partial index '{index_name}' not found"


# ============================================================================
# Unique constraints
# ============================================================================
def test_profiles_unique_constraint(pg_session):
    """profiles(platform_number, cycle_number) must have a unique constraint."""
    names = [
        r[0]
        for r in pg_session.execute(
            text(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = 'profiles'::regclass AND contype = 'u'"
            )
        ).fetchall()
    ]
    assert "uq_profiles_platform_cycle" in names


def test_float_positions_unique_constraint(pg_session):
    """float_positions(platform_number, cycle_number) must have a unique constraint."""
    names = [
        r[0]
        for r in pg_session.execute(
            text(
                "SELECT conname FROM pg_constraint"
                " WHERE conrelid = 'float_positions'::regclass AND contype = 'u'"
            )
        ).fetchall()
    ]
    assert "uq_float_positions_platform_cycle" in names


# ============================================================================
# CASCADE DELETE: profiles → measurements
# ============================================================================
def test_cascade_delete_measurements(pg_session):
    """Deleting a profile must cascade-delete its child measurements."""
    db = pg_session

    # Insert prerequisite rows via raw SQL
    db.execute(text("INSERT INTO floats (platform_number) VALUES ('CASCTEST001')"))
    float_id = db.execute(
        text("SELECT float_id FROM floats WHERE platform_number = 'CASCTEST001'")
    ).scalar()

    db.execute(text("INSERT INTO datasets (name) VALUES ('cascade_test')"))
    dataset_id = db.execute(
        text("SELECT dataset_id FROM datasets WHERE name = 'cascade_test'")
    ).scalar()

    db.execute(
        text(
            "INSERT INTO profiles (float_id, platform_number, cycle_number, dataset_id)"
            " VALUES (:fid, 'CASCTEST001', 99, :did)"
        ),
        {"fid": float_id, "did": dataset_id},
    )
    profile_id = db.execute(
        text(
            "SELECT profile_id FROM profiles"
            " WHERE platform_number = 'CASCTEST001' AND cycle_number = 99"
        )
    ).scalar()

    # Insert a measurement linked to the profile
    db.execute(
        text("INSERT INTO measurements (profile_id, pressure) VALUES (:pid, 100.0)"),
        {"pid": profile_id},
    )
    assert (
        db.execute(
            text("SELECT COUNT(*) FROM measurements WHERE profile_id = :pid"),
            {"pid": profile_id},
        ).scalar()
        == 1
    )

    # Delete the profile
    db.execute(
        text("DELETE FROM profiles WHERE profile_id = :pid"),
        {"pid": profile_id},
    )

    # Measurement must be gone (CASCADE DELETE)
    assert (
        db.execute(
            text("SELECT COUNT(*) FROM measurements WHERE profile_id = :pid"),
            {"pid": profile_id},
        ).scalar()
        == 0
    )


# ============================================================================
# Materialized views
# ============================================================================
EXPECTED_MATVIEWS = [
    "mv_float_latest_position",
    "mv_dataset_stats",
]


@pytest.mark.parametrize("view_name", EXPECTED_MATVIEWS)
def test_materialized_view_exists(pg_session, view_name):
    """Both materialized views must exist in the public schema."""
    exists = pg_session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM pg_matviews"
            "  WHERE schemaname = 'public' AND matviewname = :name"
            ")"
        ),
        {"name": view_name},
    ).scalar()
    assert exists, f"Materialized view '{view_name}' not found"


# ============================================================================
# BIGINT column types (migration 002 correction)
# ============================================================================
BIGINT_COLUMNS = [
    ("profiles", "profile_id"),
    ("measurements", "measurement_id"),
    ("measurements", "profile_id"),
]


@pytest.mark.parametrize("table_name,column_name", BIGINT_COLUMNS)
def test_bigint_column(pg_session, table_name, column_name):
    """Selected columns must be BIGINT after migration 002."""
    dtype = pg_session.execute(
        text(
            "SELECT data_type FROM information_schema.columns"
            " WHERE table_name = :tbl AND column_name = :col"
        ),
        {"tbl": table_name, "col": column_name},
    ).scalar()
    assert dtype == "bigint", f"{table_name}.{column_name} is '{dtype}', expected 'bigint'"


# ============================================================================
# PostgreSQL extensions
# ============================================================================
EXPECTED_EXTENSIONS = ["postgis", "pgcrypto", "pg_trgm"]


@pytest.mark.parametrize("ext_name", EXPECTED_EXTENSIONS)
def test_extension_enabled(pg_session, ext_name):
    """Required PostgreSQL extensions must be enabled."""
    exists = pg_session.execute(
        text(
            "SELECT EXISTS ("
            "  SELECT 1 FROM pg_extension WHERE extname = :name"
            ")"
        ),
        {"name": ext_name},
    ).scalar()
    assert exists, f"Extension '{ext_name}' is not enabled"

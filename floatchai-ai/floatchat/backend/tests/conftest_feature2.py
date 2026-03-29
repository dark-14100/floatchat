"""
Feature 2 (Ocean Data Database) test fixtures.

Provides PostgreSQL+PostGIS session and Redis client for Feature 2 tests.
These tests REQUIRE Docker services to be running:

    - PostgreSQL+PostGIS on port 5432
    - Redis on port 6379

Run ``docker-compose up -d`` and ``alembic upgrade head`` before running
these tests.  Feature 1 tests (SQLite-based) are completely unaffected.
"""

import os
from datetime import datetime, timezone

import pytest
from geoalchemy2.elements import WKTElement
from redis import Redis
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.db.models import (
    Dataset,
    Float,
    Measurement,
    OceanRegion,
    Profile,
)

# ---------------------------------------------------------------------------
# Connection URLs — override with env vars for CI
# ---------------------------------------------------------------------------
PG_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+psycopg2://floatchat:floatchat@localhost:5432/floatchat",
)
REDIS_URL = os.environ.get("TEST_REDIS_URL", "redis://localhost:6379/0")


# ---------------------------------------------------------------------------
# PostgreSQL engine (session-scoped — created once per pytest session)
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def pg_engine():
    """Create a PostgreSQL engine.  Skips all dependent tests if unreachable."""
    try:
        engine = create_engine(PG_URL, pool_pre_ping=True, pool_size=5)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        pytest.skip(f"PostgreSQL not available: {exc}")
        return  # unreachable but keeps linters happy
    yield engine
    engine.dispose()


# ---------------------------------------------------------------------------
# Transactional PostgreSQL session (function-scoped, rolls back after test)
# ---------------------------------------------------------------------------
@pytest.fixture()
def pg_session(pg_engine):
    """
    Provide a PostgreSQL session wrapped in a transaction.

    All changes made during the test are rolled back on teardown,
    leaving the database in its original state.
    """
    connection = pg_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Redis client (function-scoped, cleans ``query_cache:*`` keys on teardown)
# ---------------------------------------------------------------------------
@pytest.fixture()
def redis_client():
    """Provide a Redis client.  Skips the test if Redis is unreachable."""
    try:
        client = Redis.from_url(REDIS_URL, decode_responses=False)
        client.ping()
    except Exception as exc:
        pytest.skip(f"Redis not available: {exc}")
        return

    yield client

    # Clean up any query_cache keys created during the test
    for key in client.keys("query_cache:*"):
        client.delete(key)
    client.close()


# ---------------------------------------------------------------------------
# Test data seed fixture (function-scoped, rolled back automatically)
# ---------------------------------------------------------------------------
@pytest.fixture()
def seed_test_data(pg_session):
    """
    Insert a representative set of rows for DAL tests.

    Data layout::

        Floats:
          FCTEST001 (core)
          FCTEST002 (BGC)

        Dataset:
          "Test Dataset" (is_active=True)

        Profiles:
          [1] FCTEST001 cycle 1 — Arabian Sea (lat=10, lon=72), valid
          [2] FCTEST001 cycle 2 — same location, position_invalid=True
          [3] FCTEST002 cycle 1 — Atlantic (lat=45, lon=-30), valid

        Measurements (profile 1, 4 depth levels):
          50 dbar  — core only
          200 dbar — core + dissolved_oxygen
          500 dbar — core only
          1000 dbar — core only

        Measurements (profile 3, 1 depth level):
          100 dbar — core + dissolved_oxygen + chlorophyll

        Ocean Region:
          "Test Arabian Sea" — polygon lon 50‑80, lat 0‑30

    Returns a dict with references to all created objects.
    """
    db = pg_session

    # -- Floats ---------------------------------------------------------------
    float_core = Float(platform_number="FCTEST001", float_type="core")
    float_bgc = Float(platform_number="FCTEST002", float_type="BGC")
    db.add_all([float_core, float_bgc])
    db.flush()

    # -- Dataset --------------------------------------------------------------
    dataset = Dataset(
        name="Test Dataset", source_filename="test.nc", is_active=True,
    )
    db.add(dataset)
    db.flush()

    # -- Profiles -------------------------------------------------------------
    p_arabian = Profile(
        float_id=float_core.float_id,
        platform_number="FCTEST001",
        cycle_number=1,
        timestamp=datetime(2024, 6, 15, tzinfo=timezone.utc),
        latitude=10.0,
        longitude=72.0,
        position_invalid=False,
        geom=WKTElement("POINT(72 10)", srid=4326),
        data_mode="R",
        dataset_id=dataset.dataset_id,
    )
    p_invalid = Profile(
        float_id=float_core.float_id,
        platform_number="FCTEST001",
        cycle_number=2,
        timestamp=datetime(2024, 7, 15, tzinfo=timezone.utc),
        latitude=10.0,
        longitude=72.0,
        position_invalid=True,
        geom=None,
        data_mode="R",
        dataset_id=dataset.dataset_id,
    )
    p_atlantic = Profile(
        float_id=float_bgc.float_id,
        platform_number="FCTEST002",
        cycle_number=1,
        timestamp=datetime(2024, 8, 15, tzinfo=timezone.utc),
        latitude=45.0,
        longitude=-30.0,
        position_invalid=False,
        geom=WKTElement("POINT(-30 45)", srid=4326),
        data_mode="D",
        dataset_id=dataset.dataset_id,
    )
    db.add_all([p_arabian, p_invalid, p_atlantic])
    db.flush()

    # -- Measurements for profile 1 (core, four depth levels) -----------------
    m1 = [
        Measurement(
            profile_id=p_arabian.profile_id,
            pressure=50.0, temperature=25.0, salinity=35.0,
            pres_qc=1, temp_qc=1, psal_qc=1,
        ),
        Measurement(
            profile_id=p_arabian.profile_id,
            pressure=200.0, temperature=15.0, salinity=35.5,
            pres_qc=1, temp_qc=1, psal_qc=1,
            dissolved_oxygen=200.0, doxy_qc=1,
        ),
        Measurement(
            profile_id=p_arabian.profile_id,
            pressure=500.0, temperature=8.0, salinity=34.8,
            pres_qc=1, temp_qc=1, psal_qc=1,
        ),
        Measurement(
            profile_id=p_arabian.profile_id,
            pressure=1000.0, temperature=4.0, salinity=34.7,
            pres_qc=1, temp_qc=1, psal_qc=1,
        ),
    ]
    db.add_all(m1)

    # -- Measurements for profile 3 (BGC, one depth level) --------------------
    m3 = [
        Measurement(
            profile_id=p_atlantic.profile_id,
            pressure=100.0, temperature=12.0, salinity=35.2,
            pres_qc=1, temp_qc=1, psal_qc=1,
            dissolved_oxygen=250.0, doxy_qc=1,
            chlorophyll=0.5, chla_qc=1,
        ),
    ]
    db.add_all(m3)

    # -- Ocean Region ---------------------------------------------------------
    region = OceanRegion(
        region_name="Test Arabian Sea",
        region_type="sea",
        geom=WKTElement(
            "POLYGON((50 0, 80 0, 80 30, 50 30, 50 0))", srid=4326,
        ),
        description="Test polygon covering Arabian Sea area",
    )
    db.add(region)
    db.flush()

    return {
        "float_core": float_core,
        "float_bgc": float_bgc,
        "dataset": dataset,
        "profile_arabian": p_arabian,
        "profile_invalid": p_invalid,
        "profile_atlantic": p_atlantic,
        "measurements_p1": m1,
        "measurements_p3": m3,
        "region": region,
    }

"""
Shared pytest fixtures for integration tests.

Provides:
- SQLite in-memory database (adapted for non-PostgreSQL types)
- FastAPI TestClient with auth override
- Admin JWT token helper
- Fixture file paths
"""

import os
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text, JSON
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base

# ---------------------------------------------------------------------------
# SQLite type-compilation workarounds for Postgres-specific column types.
# We compile JSONB → JSON and Geography → TEXT so that create_all() works.
# ---------------------------------------------------------------------------
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles

try:
    from geoalchemy2 import Geography
    @compiles(Geography, "sqlite")
    def _compile_geography_sqlite(element, compiler, **kw):
        return "TEXT"
except ImportError:
    pass

@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"


# =============================================================================
# Paths to fixture NetCDF files
# =============================================================================
FIXTURES_DIR = Path(__file__).parent / "fixtures"
CORE_FILE = str(FIXTURES_DIR / "core_single_profile.nc")
BGC_FILE = str(FIXTURES_DIR / "bgc_multi_profile.nc")
MALFORMED_FILE = str(FIXTURES_DIR / "malformed_missing_psal.nc")


# =============================================================================
# SQLite in-memory engine & session (no PostGIS geometry columns)
# =============================================================================
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def test_engine():
    """Create a single in-memory SQLite engine for the session."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
    )
    # SQLite needs foreign key enforcement enabled explicitly
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


@pytest.fixture(scope="session")
def create_tables(test_engine):
    """Create all tables once per test session.
    
    NOTE: Geography/PostGIS columns will be silently skipped by SQLite.
    The models still work because geoalchemy2 columns fall back gracefully.
    """
    # Drop geom columns from table args that reference PostGIS functions
    # SQLite doesn't have func.now() either, but SQLAlchemy handles it.
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture()
def db_session(test_engine, create_tables) -> Generator[Session, None, None]:
    """Provide a transactional DB session that rolls back after each test."""
    connection = test_engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


# =============================================================================
# FastAPI TestClient with DB & auth overrides
# =============================================================================
@pytest.fixture()
def admin_token() -> str:
    """Generate a valid admin JWT for test requests."""
    from app.api.auth import create_access_token
    return create_access_token(user_id="test-admin", role="admin")


@pytest.fixture()
def user_token() -> str:
    """Generate a non-admin JWT for 403 tests."""
    from app.api.auth import create_access_token
    return create_access_token(user_id="test-user", role="user")


@pytest.fixture()
def client(db_session, admin_token) -> Generator[TestClient, None, None]:
    """
    FastAPI TestClient that:
    - Overrides get_db to use the test SQLite session
    - Does NOT override auth (callers must pass Authorization header)
    """
    from app.db.session import get_db
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()

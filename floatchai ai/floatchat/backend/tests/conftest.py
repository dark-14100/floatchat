"""
Shared pytest fixtures for integration tests.

Provides:
- SQLite in-memory database (adapted for non-PostgreSQL types)
- FastAPI TestClient with auth override
- Admin JWT token helper
- Fixture file paths
"""

# Register Feature 2 fixtures (PostgreSQL+PostGIS, Redis).
# These fixtures are only activated when a test requests them;
# Feature 1 SQLite-based tests are completely unaffected.
pytest_plugins = ["tests.conftest_feature2"]

import os
import uuid
from pathlib import Path
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text, JSON
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Base, User

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
    # Also register stub PostGIS functions so GeoAlchemy2 INSERT/SELECT works
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

        # Register stub PostGIS functions that GeoAlchemy2 generates
        dbapi_conn.create_function("ST_GeogFromText", 1, lambda x: x)
        dbapi_conn.create_function("ST_AsEWKB", 1, lambda x: x)
        dbapi_conn.create_function("ST_GeomFromEWKT", 1, lambda x: x)

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


@pytest.fixture()
def auth_user(db_session: Session) -> User:
    """Create an active researcher user for auth-protected endpoint tests."""
    user = User(
        user_id=uuid.uuid4(),
        email="auth-user@example.com",
        hashed_password="test-hash",
        name="Auth User",
        role="researcher",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def auth_token(auth_user: User) -> str:
    """Generate a valid access JWT tied to auth_user."""
    from app.auth.jwt import create_token

    return create_token(
        {
            "sub": str(auth_user.user_id),
            "email": auth_user.email,
            "role": auth_user.role,
        },
        token_type="access",
    )


@pytest.fixture()
def auth_headers(auth_token: str) -> dict[str, str]:
    """Authorization headers for protected route tests."""
    return {"Authorization": f"Bearer {auth_token}"}


@pytest.fixture()
def admin_user(db_session: Session) -> User:
    """Create an active admin user for Feature 10 admin API tests."""
    user = User(
        user_id=uuid.uuid4(),
        email="feature10-admin@example.com",
        hashed_password="test-hash",
        name="Feature 10 Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def researcher_user(db_session: Session) -> User:
    """Create an active non-admin user for Feature 10 403 checks."""
    user = User(
        user_id=uuid.uuid4(),
        email="feature10-researcher@example.com",
        hashed_password="test-hash",
        name="Feature 10 Researcher",
        role="researcher",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def admin_access_token(admin_user: User) -> str:
    """Generate Feature 13-compliant admin access token for admin router tests."""
    from app.auth.jwt import create_token

    return create_token(
        {
            "sub": str(admin_user.user_id),
            "email": admin_user.email,
            "role": admin_user.role,
        },
        token_type="access",
    )


@pytest.fixture()
def researcher_access_token(researcher_user: User) -> str:
    """Generate Feature 13-compliant non-admin access token for 403 checks."""
    from app.auth.jwt import create_token

    return create_token(
        {
            "sub": str(researcher_user.user_id),
            "email": researcher_user.email,
            "role": researcher_user.role,
        },
        token_type="access",
    )


@pytest.fixture()
def admin_headers(admin_access_token: str) -> dict[str, str]:
    """Authorization header for Feature 10 admin endpoint tests."""
    return {"Authorization": f"Bearer {admin_access_token}"}


@pytest.fixture()
def researcher_headers(researcher_access_token: str) -> dict[str, str]:
    """Authorization header for Feature 10 non-admin endpoint tests."""
    return {"Authorization": f"Bearer {researcher_access_token}"}


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

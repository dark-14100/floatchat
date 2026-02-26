"""
FloatChat Database Session Management

SQLAlchemy engine and session configuration with connection pooling.

Engines:
    - engine: Read-write engine via PgBouncer (port 5433)
    - readonly_engine: Read-only engine via PgBouncer (port 5433) using floatchat_readonly user

Dependencies:
    - get_db(): Yields a read-write session (for ingestion, admin ops)
    - get_readonly_db(): Yields a read-only session (for NL Query Engine / Feature 4)
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

# ============================================================================
# Read-write engine (application via PgBouncer on port 5433)
# ============================================================================
engine = create_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# ============================================================================
# Read-only engine (NL Query Engine via PgBouncer, floatchat_readonly user)
# ============================================================================
readonly_engine = create_engine(
    settings.READONLY_DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
    pool_pre_ping=True,
    echo=False,
)

ReadonlySessionLocal = sessionmaker(
    bind=readonly_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a read-write database session.

    Usage:
        @app.get("/items")
        def get_items(db: Session = Depends(get_db)):
            ...

    The session is automatically closed after the request completes.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_readonly_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that provides a read-only database session.

    Used exclusively by the NL Query Engine (Feature 4).
    Connects with the floatchat_readonly user — SELECT-only privileges.
    """
    db = ReadonlySessionLocal()
    try:
        yield db
    finally:
        db.close()

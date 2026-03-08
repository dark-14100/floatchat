"""
FloatChat Database Models

SQLAlchemy 2.x ORM models for the Data Ingestion Pipeline and Ocean Data Database.
Tables are defined in FK-dependency order for migration compatibility.

Tables:
    1. floats - One row per ARGO float
    2. datasets - One row per ingested file
    3. profiles - One row per float cycle
    4. measurements - One row per depth level
    5. float_positions - Lightweight spatial index
    6. ingestion_jobs - Job tracking
    7. ocean_regions - Named ocean basin polygons (Feature 2)
    8. dataset_versions - Dataset version audit log (Feature 2)
    9. dataset_embeddings - Vector embeddings per dataset (Feature 3)
    10. float_embeddings - Vector embeddings per float (Feature 3)
    11. chat_sessions - One row per conversation session (Feature 5)
    12. chat_messages - One row per message in a conversation (Feature 5)
    13. users - One row per authenticated user (Feature 13)
    14. password_reset_tokens - Password reset flow tokens (Feature 13)
    15. query_history - Successful NL query history for RAG retrieval (Feature 14)
    16. admin_audit_log - Admin action audit trail (Feature 10)
    17. anomalies - Nightly detected contextual anomalies (Feature 15)
    18. anomaly_baselines - Seasonal/monthly anomaly baselines (Feature 15)
    19. gdac_sync_runs - GDAC synchronization run history
    20. gdac_sync_state - GDAC synchronization checkpoint state

Materialized Views:
    - mv_float_latest_position - Latest position per float
    - mv_dataset_stats - Per-dataset aggregated stats
"""

from datetime import datetime
from typing import Optional
import uuid

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
import sqlalchemy as sa
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


# =============================================================================
# Table 1: floats
# =============================================================================
class Float(Base):
    """
    One record per unique ARGO float (identified by platform_number).
    
    The platform_number is the WMO ID - they are the same value in ARGO.
    """
    __tablename__ = "floats"

    float_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_number: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    wmo_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    float_type: Mapped[Optional[str]] = mapped_column(
        String(10),
        CheckConstraint("float_type IN ('core', 'BGC', 'deep')"),
        nullable=True
    )
    deployment_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deployment_lat: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    deployment_lon: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    program: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    profiles: Mapped[list["Profile"]] = relationship("Profile", back_populates="float_ref")


# =============================================================================
# Table 2: datasets
# =============================================================================
class Dataset(Base):
    """
    One record per ingested NetCDF file.
    
    For ZIP uploads, each .nc file inside creates its own dataset record.
    """
    __tablename__ = "datasets"

    dataset_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    ingestion_date: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    date_range_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    date_range_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    bbox = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )
    float_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profile_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    variable_list: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    summary_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_public: Mapped[bool] = mapped_column(
        Boolean,
        server_default=sa.text("true"),
        nullable=False,
    )
    tags: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    dataset_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    profiles: Mapped[list["Profile"]] = relationship("Profile", back_populates="dataset")
    ingestion_jobs: Mapped[list["IngestionJob"]] = relationship("IngestionJob", back_populates="dataset")
    versions: Mapped[list["DatasetVersion"]] = relationship("DatasetVersion", back_populates="dataset")


# =============================================================================
# Table 3: profiles
# =============================================================================
class Profile(Base):
    """
    One record per float cycle.
    
    Contains profile-level metadata and a PostGIS geometry point for spatial queries.
    """
    __tablename__ = "profiles"

    profile_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    float_id: Mapped[int] = mapped_column(Integer, ForeignKey("floats.float_id"), nullable=False)
    platform_number: Mapped[str] = mapped_column(String(20), nullable=False)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    juld_raw: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    timestamp_missing: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    latitude: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    position_invalid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    geom = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    data_mode: Mapped[Optional[str]] = mapped_column(
        String(1),
        CheckConstraint("data_mode IN ('R', 'A', 'D')"),
        nullable=True
    )
    dataset_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("datasets.dataset_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Unique constraint on (platform_number, cycle_number)
    __table_args__ = (
        UniqueConstraint("platform_number", "cycle_number", name="uq_profiles_platform_cycle"),
    )

    # Relationships
    float_ref: Mapped["Float"] = relationship("Float", back_populates="profiles")
    dataset: Mapped[Optional["Dataset"]] = relationship("Dataset", back_populates="profiles")
    measurements: Mapped[list["Measurement"]] = relationship(
        "Measurement", back_populates="profile", cascade="all, delete-orphan"
    )


# =============================================================================
# Table 4: measurements
# =============================================================================
class Measurement(Base):
    """
    One record per depth level within a profile.
    
    Contains all oceanographic variables and their QC flags.
    """
    __tablename__ = "measurements"

    measurement_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("profiles.profile_id", ondelete="CASCADE"), nullable=False
    )
    
    # Core oceanographic variables
    pressure: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    temperature: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    salinity: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    
    # BGC (Biogeochemical) variables - optional
    dissolved_oxygen: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    chlorophyll: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    nitrate: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    ph: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    bbp700: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    downwelling_irradiance: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    
    # QC flags (ARGO standard: 0=no QC, 1=good, 2=probably good, 3=probably bad, 4=bad, 9=missing)
    pres_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    temp_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    psal_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    doxy_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    chla_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    nitrate_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    ph_qc: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    
    # Outlier flag (set by cleaner module)
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    profile: Mapped["Profile"] = relationship("Profile", back_populates="measurements")


# =============================================================================
# Table 5: float_positions
# =============================================================================
class FloatPosition(Base):
    """
    Lightweight spatial index for float positions.
    
    One record per (platform_number, cycle_number) for fast map queries.
    This is a denormalized copy of profile positions for performance.
    """
    __tablename__ = "float_positions"

    position_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform_number: Mapped[str] = mapped_column(String(20), nullable=False)
    cycle_number: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    latitude: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    geom = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )

    # Unique constraint on (platform_number, cycle_number)
    __table_args__ = (
        UniqueConstraint("platform_number", "cycle_number", name="uq_float_positions_platform_cycle"),
    )


# =============================================================================
# Table 6: ingestion_jobs
# =============================================================================
class IngestionJob(Base):
    """
    Tracks every ingestion job.
    
    Status transitions: pending → running → succeeded/failed
    """
    __tablename__ = "ingestion_jobs"

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    dataset_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("datasets.dataset_id"), nullable=True
    )
    original_filename: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    raw_file_path: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("status IN ('pending', 'running', 'succeeded', 'failed')"),
        default="pending",
        nullable=False
    )
    progress_pct: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    profiles_total: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profiles_ingested: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_log: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    errors: Mapped[Optional[list]] = mapped_column(JSONB, default=list, nullable=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str] = mapped_column(
        String(50),
        CheckConstraint("source IN ('manual_upload', 'gdac_sync')"),
        server_default=sa.text("'manual_upload'"),
        nullable=False,
    )

    # Relationships
    dataset: Mapped[Optional["Dataset"]] = relationship("Dataset", back_populates="ingestion_jobs")


# =============================================================================
# Table 7: ocean_regions (Feature 2)
# =============================================================================
class OceanRegion(Base):
    """
    Named ocean basin polygons for region-based spatial filtering.

    Supports hierarchical regions: ocean basins contain sub-regions
    (e.g., Arabian Sea → Indian Ocean).
    """
    __tablename__ = "ocean_regions"

    region_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region_name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    region_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        CheckConstraint("region_type IN ('ocean', 'sea', 'bay', 'gulf')"),
        nullable=True,
    )
    parent_region_id: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("ocean_regions.region_id"),
        nullable=True,
    )
    geom = mapped_column(
        Geography(geometry_type="POLYGON", srid=4326, spatial_index=False),
        nullable=True,
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Self-referencing relationship
    parent: Mapped[Optional["OceanRegion"]] = relationship(
        "OceanRegion", remote_side=[region_id], backref="children"
    )


# =============================================================================
# Table 8: dataset_versions (Feature 2)
# =============================================================================
class DatasetVersion(Base):
    """
    Audit log of dataset version history for rollback support.

    A new record is created each time a dataset is re-ingested.
    """
    __tablename__ = "dataset_versions"

    version_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("datasets.dataset_id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    ingestion_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    profile_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    float_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    dataset: Mapped["Dataset"] = relationship("Dataset", back_populates="versions")


# =============================================================================
# Table 9: dataset_embeddings (Feature 3)
# =============================================================================
class DatasetEmbedding(Base):
    """
    Vector embedding for a dataset's summary and metadata.

    Used by the Metadata Search Engine for semantic similarity search.
    One row per dataset — upserted on each indexing run.
    """
    __tablename__ = "dataset_embeddings"

    embedding_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("datasets.dataset_id"), nullable=False, unique=True
    )
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("status IN ('indexed', 'embedding_failed')"),
        nullable=False,
        server_default="indexed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # One-directional relationship — Dataset model is not modified
    dataset: Mapped["Dataset"] = relationship("Dataset")


# =============================================================================
# Table 10: float_embeddings (Feature 3)
# =============================================================================
class FloatEmbedding(Base):
    """
    Vector embedding for a float's metadata and characteristics.

    Used by the Metadata Search Engine for semantic similarity search.
    One row per float — upserted on each indexing run.
    """
    __tablename__ = "float_embeddings"

    embedding_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    float_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("floats.float_id"), nullable=False, unique=True
    )
    embedding_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        CheckConstraint("status IN ('indexed', 'embedding_failed')"),
        nullable=False,
        server_default="indexed",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # One-directional relationship — Float model is not modified
    float_ref: Mapped["Float"] = relationship("Float")


# =============================================================================
# Materialized View table objects (Feature 2)
# Read-only reflections — no ORM insert/update, used by DAL queries only.
# =============================================================================
mv_float_latest_position = Table(
    "mv_float_latest_position",
    Base.metadata,
    Column("platform_number", String(20)),
    Column("float_id", Integer),
    Column("cycle_number", Integer),
    Column("timestamp", DateTime(timezone=True)),
    Column("latitude", Double),
    Column("longitude", Double),
    Column("geom", Geography(geometry_type="POINT", srid=4326, spatial_index=False)),
)

mv_dataset_stats = Table(
    "mv_dataset_stats",
    Base.metadata,
    Column("dataset_id", Integer),
    Column("name", String(255)),
    Column("profile_count", BigInteger),
    Column("float_count", BigInteger),
    Column("date_range_start", DateTime(timezone=True)),
    Column("date_range_end", DateTime(timezone=True)),
)


# =============================================================================
# 11. Chat Sessions (Feature 5)
# =============================================================================
class ChatSession(Base):
    """One row per conversation session."""
    __tablename__ = "chat_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_identifier: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True, index=True
    )
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=sa.text("true"), nullable=False
    )
    message_count: Mapped[int] = mapped_column(
        Integer, server_default=sa.text("0"), nullable=False
    )

    # Relationships
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage",
        back_populates="session",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


# =============================================================================
# 12. Chat Messages (Feature 5)
# =============================================================================
class ChatMessage(Base):
    """One row per message in a conversation."""
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.session_id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # 'user' or 'assistant'
    content: Mapped[str] = mapped_column(Text, nullable=False)
    nl_query: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    generated_sql: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    result_metadata: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    follow_up_suggestions: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    status: Mapped[Optional[str]] = mapped_column(
        String(30), nullable=True
    )  # pending_confirmation | confirmed | completed | error
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    session: Mapped["ChatSession"] = relationship(
        "ChatSession", back_populates="messages"
    )


# =============================================================================
# 13. Users (Feature 13)
# =============================================================================
class User(Base):
    """One row per authenticated user account."""
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("role IN ('researcher', 'admin')", name="ck_users_role"),
        Index("ix_users_email", "email", unique=True),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(
        String(20),
        server_default=sa.text("'researcher'"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, server_default=sa.text("true"), nullable=False
    )

    # Relationships
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )


# =============================================================================
# 14. Admin Audit Log (Feature 10)
# =============================================================================
class AdminAuditLog(Base):
    """Append-only audit trail for all state-changing admin actions."""
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        Index("ix_admin_audit_log_admin_user_id", "admin_user_id"),
        Index("ix_admin_audit_log_created_at", "created_at"),
        Index("ix_admin_audit_log_entity_type_entity_id", "entity_type", "entity_id"),
        CheckConstraint(
            "action IN ('dataset_upload_started', 'dataset_soft_deleted', 'dataset_hard_deleted', "
            "'dataset_metadata_updated', 'dataset_summary_regenerated', 'dataset_visibility_changed', "
            "'ingestion_job_retried', 'hard_delete_requested', 'hard_delete_completed', "
            "'gdac_sync_triggered')",
            name="ck_admin_audit_log_action",
        ),
        CheckConstraint(
            "entity_type IN ('dataset', 'ingestion_job', 'gdac_sync_run')",
            name="ck_admin_audit_log_entity_type",
        ),
    )

    log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    admin_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # One-directional relationship keeps existing User model additive-only.
    admin_user: Mapped[Optional["User"]] = relationship("User")


# =============================================================================
# 15. Password Reset Tokens (Feature 13)
# =============================================================================
class PasswordResetToken(Base):
    """Password reset tokens stored as hashes with expiry and used flag."""
    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_tokens_token_hash", "token_hash"),
    )

    token_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(
        Boolean, server_default=sa.text("false"), nullable=False
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="password_reset_tokens")


# =============================================================================
# 16. Query History (Feature 14)
# =============================================================================
class QueryHistory(Base):
    """Successful query history used for tenant-scoped RAG retrieval."""
    __tablename__ = "query_history"
    __table_args__ = (
        Index("ix_query_history_user_id", "user_id"),
        Index("ix_query_history_created_at", "created_at"),
    )

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nl_query: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="CASCADE"),
        nullable=False,
    )
    session_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("chat_sessions.session_id", ondelete="SET NULL"),
        nullable=True,
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # One-directional relationships keep existing models additive-only.
    user: Mapped["User"] = relationship("User")
    session: Mapped[Optional["ChatSession"]] = relationship("ChatSession")


# =============================================================================
# 17. Anomalies (Feature 15)
# =============================================================================
class Anomaly(Base):
    """Contextually unusual profile reading detected by nightly anomaly scan."""
    __tablename__ = "anomalies"
    __table_args__ = (
        Index("ix_anomalies_detected_at", "detected_at"),
        Index("ix_anomalies_float_id", "float_id"),
        Index("ix_anomalies_is_reviewed_detected_at", "is_reviewed", "detected_at"),
        Index("ix_anomalies_severity", "severity"),
        CheckConstraint(
            "anomaly_type IN ('spatial_baseline', 'float_self_comparison', 'cluster_pattern', 'seasonal_baseline')",
            name="ck_anomalies_anomaly_type",
        ),
        CheckConstraint(
            "severity IN ('low', 'medium', 'high')",
            name="ck_anomalies_severity",
        ),
    )

    anomaly_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    float_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("floats.float_id"),
        nullable=False,
    )
    profile_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("profiles.profile_id"),
        nullable=False,
    )
    anomaly_type: Mapped[str] = mapped_column(String(50), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    variable: Mapped[str] = mapped_column(String(50), nullable=False)
    baseline_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    observed_value: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    deviation_percent: Mapped[Optional[float]] = mapped_column(Double, nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    region: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_reviewed: Mapped[bool] = mapped_column(
        Boolean,
        server_default=sa.text("false"),
        nullable=False,
    )
    reviewed_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.user_id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # One-directional relationships keep existing models additive-only.
    float_ref: Mapped["Float"] = relationship("Float")
    profile: Mapped["Profile"] = relationship("Profile")
    reviewer: Mapped[Optional["User"]] = relationship("User")


# =============================================================================
# 18. Anomaly Baselines (Feature 15)
# =============================================================================
class AnomalyBaseline(Base):
    """Pre-computed monthly baselines by region/variable for seasonal detection."""
    __tablename__ = "anomaly_baselines"
    __table_args__ = (
        UniqueConstraint(
            "region",
            "variable",
            "month",
            name="uq_anomaly_baselines_region_variable_month",
        ),
        Index(
            "ix_anomaly_baselines_region_variable_month",
            "region",
            "variable",
            "month",
        ),
        CheckConstraint("month BETWEEN 1 AND 12", name="ck_anomaly_baselines_month"),
    )

    baseline_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    variable: Mapped[str] = mapped_column(String(50), nullable=False)
    month: Mapped[int] = mapped_column(Integer, nullable=False)
    mean_value: Mapped[float] = mapped_column(Double, nullable=False)
    std_dev: Mapped[float] = mapped_column(Double, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# =============================================================================
# 19. GDAC Sync Runs
# =============================================================================
class GDACSyncRun(Base):
    """GDAC synchronization run history and aggregate counters."""

    __tablename__ = "gdac_sync_runs"
    __table_args__ = (
        Index("ix_gdac_sync_runs_started_at", "started_at"),
        Index("ix_gdac_sync_runs_status", "status"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'partial')",
            name="ck_gdac_sync_runs_status",
        ),
        CheckConstraint(
            "triggered_by IN ('scheduled', 'manual')",
            name="ck_gdac_sync_runs_triggered_by",
        ),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    index_profiles_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profiles_downloaded: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profiles_ingested: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    profiles_skipped: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    gdac_mirror: Mapped[str] = mapped_column(String(100), nullable=False)
    lookback_days: Mapped[int] = mapped_column(Integer, nullable=False)
    triggered_by: Mapped[str] = mapped_column(String(20), nullable=False)


# =============================================================================
# 20. GDAC Sync State
# =============================================================================
class GDACSyncState(Base):
    """Key-value checkpoint state for GDAC synchronization."""

    __tablename__ = "gdac_sync_state"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

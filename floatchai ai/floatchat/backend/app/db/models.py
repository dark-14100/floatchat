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

Materialized Views:
    - mv_float_latest_position - Latest position per float
    - mv_dataset_stats - Per-dataset aggregated stats
"""

from datetime import datetime
from typing import Optional
import uuid

from geoalchemy2 import Geography
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
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
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

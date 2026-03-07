"""Feature 15 Anomaly Detection API router."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Optional
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.anomaly.baselines import compute_all_baselines
from app.auth.dependencies import get_current_admin_user, get_current_user
from app.db.models import Anomaly, Float, Measurement, Profile, User, mv_float_latest_position
from app.db.session import get_db, get_readonly_db

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/anomalies", tags=["Anomalies"])


class AnomalyListItemResponse(BaseModel):
    anomaly_id: str
    float_id: int
    profile_id: int
    anomaly_type: str
    severity: str
    variable: str
    baseline_value: Optional[float] = None
    observed_value: Optional[float] = None
    deviation_percent: Optional[float] = None
    description: str
    detected_at: str
    region: Optional[str] = None
    is_reviewed: bool
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    platform_number: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class AnomalyListResponse(BaseModel):
    items: list[AnomalyListItemResponse]
    total: int
    limit: int
    offset: int


class MeasurementRow(BaseModel):
    pressure: Optional[float] = None
    temperature: Optional[float] = None
    salinity: Optional[float] = None
    dissolved_oxygen: Optional[float] = None
    chlorophyll: Optional[float] = None
    nitrate: Optional[float] = None
    ph: Optional[float] = None
    bbp700: Optional[float] = None
    downwelling_irradiance: Optional[float] = None


class AnomalyDetailResponse(BaseModel):
    anomaly_id: str
    float_id: int
    profile_id: int
    anomaly_type: str
    severity: str
    variable: str
    baseline_value: Optional[float] = None
    observed_value: Optional[float] = None
    deviation_percent: Optional[float] = None
    description: str
    detected_at: str
    region: Optional[str] = None
    is_reviewed: bool
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None

    platform_number: str
    float_type: Optional[str] = None
    deployment_date: Optional[str] = None
    deployment_lat: Optional[float] = None
    deployment_lon: Optional[float] = None
    country: Optional[str] = None
    program: Optional[str] = None

    profile_timestamp: Optional[str] = None
    profile_latitude: Optional[float] = None
    profile_longitude: Optional[float] = None
    measurements: list[MeasurementRow]

    baseline_comparison: dict[str, Optional[float]]


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    return float(value)


def _parse_uuid(value: str, field_name: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid {field_name} format") from exc


@router.get("", response_model=AnomalyListResponse, dependencies=[Depends(get_current_user)])
def list_anomalies(
    severity: Optional[str] = Query(default=None),
    anomaly_type: Optional[str] = Query(default=None),
    variable: Optional[str] = Query(default=None),
    is_reviewed: Optional[bool] = Query(default=None),
    days: int = Query(default=7, ge=1, le=365),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_readonly_db),
) -> AnomalyListResponse:
    """List anomalies with pagination and filters."""
    cutoff = datetime.now(UTC) - timedelta(days=days)

    filters = [Anomaly.detected_at >= cutoff]
    if severity:
        filters.append(Anomaly.severity == severity)
    if anomaly_type:
        filters.append(Anomaly.anomaly_type == anomaly_type)
    if variable:
        filters.append(Anomaly.variable == variable)
    if is_reviewed is not None:
        filters.append(Anomaly.is_reviewed.is_(is_reviewed))

    total = db.execute(
        select(func.count(Anomaly.anomaly_id)).where(*filters)
    ).scalar_one()

    stmt = (
        select(
            Anomaly,
            Float.platform_number,
            mv_float_latest_position.c.latitude,
            mv_float_latest_position.c.longitude,
        )
        .join(Float, Float.float_id == Anomaly.float_id)
        .outerjoin(
            mv_float_latest_position,
            mv_float_latest_position.c.float_id == Anomaly.float_id,
        )
        .where(*filters)
        .order_by(Anomaly.detected_at.desc())
        .offset(offset)
        .limit(limit)
    )

    rows = db.execute(stmt).all()

    items: list[AnomalyListItemResponse] = []
    for anomaly, platform_number, latitude, longitude in rows:
        items.append(
            AnomalyListItemResponse(
                anomaly_id=str(anomaly.anomaly_id),
                float_id=anomaly.float_id,
                profile_id=anomaly.profile_id,
                anomaly_type=anomaly.anomaly_type,
                severity=anomaly.severity,
                variable=anomaly.variable,
                baseline_value=_to_float(anomaly.baseline_value),
                observed_value=_to_float(anomaly.observed_value),
                deviation_percent=_to_float(anomaly.deviation_percent),
                description=anomaly.description,
                detected_at=_iso(anomaly.detected_at) or "",
                region=anomaly.region,
                is_reviewed=anomaly.is_reviewed,
                reviewed_by=str(anomaly.reviewed_by) if anomaly.reviewed_by else None,
                reviewed_at=_iso(anomaly.reviewed_at),
                platform_number=platform_number,
                latitude=_to_float(latitude),
                longitude=_to_float(longitude),
            )
        )

    return AnomalyListResponse(items=items, total=int(total), limit=limit, offset=offset)


@router.get("/{anomaly_id}", response_model=AnomalyDetailResponse, dependencies=[Depends(get_current_user)])
def get_anomaly_detail(
    anomaly_id: str,
    db: Session = Depends(get_readonly_db),
) -> AnomalyDetailResponse:
    """Get full anomaly detail including float metadata and profile measurements."""
    anomaly_uuid = _parse_uuid(anomaly_id, "anomaly_id")

    anomaly = db.execute(
        select(Anomaly).where(Anomaly.anomaly_id == anomaly_uuid)
    ).scalar_one_or_none()
    if anomaly is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    float_row = db.execute(
        select(Float).where(Float.float_id == anomaly.float_id)
    ).scalar_one_or_none()
    if float_row is None:
        raise HTTPException(status_code=404, detail="Anomaly float not found")

    profile = db.execute(
        select(Profile).where(Profile.profile_id == anomaly.profile_id)
    ).scalar_one_or_none()

    measurement_rows = db.execute(
        select(
            Measurement.pressure,
            Measurement.temperature,
            Measurement.salinity,
            Measurement.dissolved_oxygen,
            Measurement.chlorophyll,
            Measurement.nitrate,
            Measurement.ph,
            Measurement.bbp700,
            Measurement.downwelling_irradiance,
        )
        .where(
            Measurement.profile_id == anomaly.profile_id,
            Measurement.is_outlier.is_(False),
        )
        .order_by(Measurement.pressure.asc())
    ).all()

    measurements = [
        MeasurementRow(
            pressure=_to_float(row.pressure),
            temperature=_to_float(row.temperature),
            salinity=_to_float(row.salinity),
            dissolved_oxygen=_to_float(row.dissolved_oxygen),
            chlorophyll=_to_float(row.chlorophyll),
            nitrate=_to_float(row.nitrate),
            ph=_to_float(row.ph),
            bbp700=_to_float(row.bbp700),
            downwelling_irradiance=_to_float(row.downwelling_irradiance),
        )
        for row in measurement_rows
    ]

    return AnomalyDetailResponse(
        anomaly_id=str(anomaly.anomaly_id),
        float_id=anomaly.float_id,
        profile_id=anomaly.profile_id,
        anomaly_type=anomaly.anomaly_type,
        severity=anomaly.severity,
        variable=anomaly.variable,
        baseline_value=_to_float(anomaly.baseline_value),
        observed_value=_to_float(anomaly.observed_value),
        deviation_percent=_to_float(anomaly.deviation_percent),
        description=anomaly.description,
        detected_at=_iso(anomaly.detected_at) or "",
        region=anomaly.region,
        is_reviewed=anomaly.is_reviewed,
        reviewed_by=str(anomaly.reviewed_by) if anomaly.reviewed_by else None,
        reviewed_at=_iso(anomaly.reviewed_at),
        platform_number=float_row.platform_number,
        float_type=float_row.float_type,
        deployment_date=_iso(float_row.deployment_date),
        deployment_lat=_to_float(float_row.deployment_lat),
        deployment_lon=_to_float(float_row.deployment_lon),
        country=float_row.country,
        program=float_row.program,
        profile_timestamp=_iso(profile.timestamp) if profile else None,
        profile_latitude=_to_float(profile.latitude) if profile else None,
        profile_longitude=_to_float(profile.longitude) if profile else None,
        measurements=measurements,
        baseline_comparison={
            "baseline_value": _to_float(anomaly.baseline_value),
            "observed_value": _to_float(anomaly.observed_value),
            "deviation_percent": _to_float(anomaly.deviation_percent),
        },
    )


@router.patch("/{anomaly_id}/review", response_model=AnomalyListItemResponse)
def mark_anomaly_reviewed(
    anomaly_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> AnomalyListItemResponse:
    """Mark anomaly as reviewed by current authenticated user."""
    anomaly_uuid = _parse_uuid(anomaly_id, "anomaly_id")

    anomaly = db.execute(
        select(Anomaly).where(Anomaly.anomaly_id == anomaly_uuid)
    ).scalar_one_or_none()
    if anomaly is None:
        raise HTTPException(status_code=404, detail="Anomaly not found")

    if anomaly.is_reviewed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Anomaly already reviewed",
        )

    anomaly.is_reviewed = True
    anomaly.reviewed_by = current_user.user_id
    anomaly.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(anomaly)

    platform_row = db.execute(
        select(Float.platform_number).where(Float.float_id == anomaly.float_id)
    ).one()

    latest_position = db.execute(
        select(
            mv_float_latest_position.c.latitude,
            mv_float_latest_position.c.longitude,
        ).where(mv_float_latest_position.c.float_id == anomaly.float_id)
    ).one_or_none()

    return AnomalyListItemResponse(
        anomaly_id=str(anomaly.anomaly_id),
        float_id=anomaly.float_id,
        profile_id=anomaly.profile_id,
        anomaly_type=anomaly.anomaly_type,
        severity=anomaly.severity,
        variable=anomaly.variable,
        baseline_value=_to_float(anomaly.baseline_value),
        observed_value=_to_float(anomaly.observed_value),
        deviation_percent=_to_float(anomaly.deviation_percent),
        description=anomaly.description,
        detected_at=_iso(anomaly.detected_at) or "",
        region=anomaly.region,
        is_reviewed=anomaly.is_reviewed,
        reviewed_by=str(anomaly.reviewed_by) if anomaly.reviewed_by else None,
        reviewed_at=_iso(anomaly.reviewed_at),
        platform_number=platform_row.platform_number,
        latitude=_to_float(latest_position.latitude) if latest_position else None,
        longitude=_to_float(latest_position.longitude) if latest_position else None,
    )


class BaselineComputeResponse(BaseModel):
    message: str
    summary: dict[str, Any]


@router.post(
    "/baselines/compute",
    response_model=BaselineComputeResponse,
    dependencies=[Depends(get_current_admin_user)],
)
def compute_baselines_admin(
    db: Session = Depends(get_db),
) -> BaselineComputeResponse:
    """Admin endpoint to recompute anomaly seasonal baselines."""
    try:
        summary = compute_all_baselines(db)
        db.commit()
    except Exception as exc:
        db.rollback()
        log.error("anomaly_baseline_compute_failed", error=str(exc))
        raise HTTPException(status_code=500, detail="Baseline computation failed") from exc

    return BaselineComputeResponse(
        message="Baseline computation complete",
        summary=summary,
    )

"""
FloatChat Geospatial Map API Router (Feature 7)

Endpoints:
  GET  /map/active-floats
  GET  /map/nearest-floats
  POST /map/radius-query
  GET  /map/floats/{platform_number}
  GET  /map/basin-floats
  GET  /map/basin-polygons
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.dal import get_profiles_by_radius
from app.db.models import Float, Measurement, OceanRegion, Profile, mv_float_latest_position
from app.db.session import get_readonly_db
from app.search.discovery import resolve_region_name

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/map", tags=["Map"])


# ── Request/Response Models ────────────────────────────────────────────────

class ActiveFloatResponse(BaseModel):
    platform_number: str
    float_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_seen: Optional[str] = None


class NearestFloatResponse(BaseModel):
    float_id: int
    platform_number: str
    float_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    distance_km: float
    last_seen: Optional[str] = None


class RadiusQueryRequest(BaseModel):
    lat: float
    lon: float
    radius_km: float = Field(..., gt=0)
    variables: Optional[list[str]] = None


class RadiusQueryResponse(BaseModel):
    profile_count: int
    float_count: int
    profiles: list[dict[str, Any]]
    bbox: Optional[dict[str, Any]] = None


class RecentProfileResponse(BaseModel):
    cycle_number: int
    timestamp: Optional[str] = None
    pressure_levels: list[float]
    temperature_levels: list[float]


class FloatDetailResponse(BaseModel):
    platform_number: str
    wmo_id: Optional[str] = None
    float_type: Optional[str] = None
    deployment_date: Optional[str] = None
    deployment_lat: Optional[float] = None
    deployment_lon: Optional[float] = None
    country: Optional[str] = None
    program: Optional[str] = None
    last_profile_date: Optional[str] = None
    last_latitude: Optional[float] = None
    last_longitude: Optional[float] = None
    cycle_count: int
    active_date_range_start: Optional[str] = None
    active_date_range_end: Optional[str] = None
    recent_profiles: list[RecentProfileResponse]


class BasinFloatResponse(BaseModel):
    float_id: int
    platform_number: str
    float_type: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    last_seen: Optional[str] = None


class BasinPolygonsResponse(BaseModel):
    type: str
    features: list[dict[str, Any]]


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_redis_client() -> Optional[Redis]:
    """
    Create Redis client for map endpoint caching.
    Returns None when Redis is unavailable.
    """
    try:
        settings = get_settings()
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        log.warning("redis_unavailable_for_map", error=str(exc))
        return None


def _iso(ts: Optional[datetime]) -> Optional[str]:
    return ts.isoformat() if ts else None


def _validate_lat_lon(lat: float, lon: float) -> None:
    if lat < -90 or lat > 90:
        raise HTTPException(status_code=400, detail="Latitude must be between -90 and 90")
    if lon < -180 or lon > 180:
        raise HTTPException(status_code=400, detail="Longitude must be between -180 and 180")


def _profiles_bbox_geojson(profiles: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    points = [
        (row.get("longitude"), row.get("latitude"))
        for row in profiles
        if row.get("latitude") is not None and row.get("longitude") is not None
    ]
    if not points:
        return None

    lon_values = [p[0] for p in points]
    lat_values = [p[1] for p in points]
    min_lon, max_lon = min(lon_values), max(lon_values)
    min_lat, max_lat = min(lat_values), max(lat_values)

    return {
        "type": "Polygon",
        "coordinates": [[
            [min_lon, min_lat],
            [max_lon, min_lat],
            [max_lon, max_lat],
            [min_lon, max_lat],
            [min_lon, min_lat],
        ]],
    }


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/active-floats", response_model=list[ActiveFloatResponse])
def get_active_floats(db: Session = Depends(get_readonly_db)) -> list[dict[str, Any]]:
    """Return latest position for all active floats, cached in Redis."""
    start = time.perf_counter()
    settings = get_settings()
    cache_key = "map_active_floats"

    log.info("map_active_floats_request")

    redis_client = _get_redis_client()
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                log.info("map_active_floats_cache_hit", count=len(data))
                return data
        except Exception:
            log.warning("map_active_floats_cache_read_failed", exc_info=True)

    stmt = (
        select(
            mv_float_latest_position.c.platform_number,
            Float.float_type,
            mv_float_latest_position.c.latitude,
            mv_float_latest_position.c.longitude,
            mv_float_latest_position.c.timestamp,
        )
        .select_from(
            mv_float_latest_position.join(
                Float,
                mv_float_latest_position.c.float_id == Float.float_id,
            )
        )
        .order_by(mv_float_latest_position.c.platform_number.asc())
    )

    rows = db.execute(stmt).all()
    payload = [
        {
            "platform_number": row.platform_number,
            "float_type": row.float_type,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "last_seen": _iso(row.timestamp),
        }
        for row in rows
    ]

    if redis_client:
        try:
            redis_client.set(cache_key, json.dumps(payload), ex=settings.MAP_ACTIVE_FLOATS_CACHE_TTL)
            log.info(
                "map_active_floats_cache_set",
                ttl_seconds=settings.MAP_ACTIVE_FLOATS_CACHE_TTL,
                count=len(payload),
            )
        except Exception:
            log.warning("map_active_floats_cache_write_failed", exc_info=True)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info("map_active_floats_response", count=len(payload), elapsed_ms=elapsed_ms)
    return payload


@router.get("/nearest-floats", response_model=list[NearestFloatResponse])
def get_nearest_floats(
    lat: float,
    lon: float,
    n: int = Query(default=None),
    max_distance_km: float = Query(default=None),
    db: Session = Depends(get_readonly_db),
) -> list[dict[str, Any]]:
    """Return N nearest active floats to a given point."""
    start = time.perf_counter()
    settings = get_settings()

    _validate_lat_lon(lat, lon)

    effective_n = n if n is not None else settings.MAP_NEAREST_FLOATS_DEFAULT_N
    effective_n = min(effective_n, settings.MAP_NEAREST_FLOATS_MAX_N)
    effective_max_distance_km = (
        max_distance_km if max_distance_km is not None else settings.MAP_NEAREST_FLOATS_DEFAULT_RADIUS_KM
    )

    log.info(
        "map_nearest_floats_request",
        lat=lat,
        lon=lon,
        n_requested=n,
        n_effective=effective_n,
        max_distance_km=effective_max_distance_km,
    )

    point_wkt = f"SRID=4326;POINT({lon} {lat})"
    point_geog = func.ST_GeogFromText(point_wkt)
    distance_expr = (func.ST_Distance(mv_float_latest_position.c.geom, point_geog) / 1000.0).label("distance_km")

    stmt = (
        select(
            mv_float_latest_position.c.float_id,
            mv_float_latest_position.c.platform_number,
            Float.float_type,
            mv_float_latest_position.c.latitude,
            mv_float_latest_position.c.longitude,
            mv_float_latest_position.c.timestamp,
            distance_expr,
        )
        .select_from(
            mv_float_latest_position.join(
                Float,
                mv_float_latest_position.c.float_id == Float.float_id,
            )
        )
        .where(
            func.ST_DWithin(
                mv_float_latest_position.c.geom,
                point_geog,
                effective_max_distance_km * 1000.0,
            )
        )
        .order_by(distance_expr.asc())
        .limit(effective_n)
    )

    rows = db.execute(stmt).all()
    payload = [
        {
            "float_id": row.float_id,
            "platform_number": row.platform_number,
            "float_type": row.float_type,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "distance_km": round(float(row.distance_km), 1),
            "last_seen": _iso(row.timestamp),
        }
        for row in rows
    ]

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info("map_nearest_floats_response", count=len(payload), elapsed_ms=elapsed_ms)
    return payload


@router.post("/radius-query", response_model=RadiusQueryResponse)
def post_radius_query(
    body: RadiusQueryRequest,
    db: Session = Depends(get_readonly_db),
) -> dict[str, Any]:
    """Return profile metadata for profiles within a radius."""
    start = time.perf_counter()
    settings = get_settings()

    _validate_lat_lon(body.lat, body.lon)

    log.info(
        "map_radius_query_request",
        lat=body.lat,
        lon=body.lon,
        radius_km=body.radius_km,
        variables=body.variables,
    )

    if body.radius_km > settings.MAP_RADIUS_QUERY_MAX_KM:
        raise HTTPException(
            status_code=400,
            detail=f"Radius {body.radius_km}km exceeds maximum of {settings.MAP_RADIUS_QUERY_MAX_KM}km",
        )

    profiles = get_profiles_by_radius(
        body.lat,
        body.lon,
        body.radius_km * 1000.0,
        None,
        None,
        db=db,
    )

    float_count = len({row.get("platform_number") for row in profiles if row.get("platform_number")})
    bbox = _profiles_bbox_geojson(profiles)

    payload = {
        "profile_count": len(profiles),
        "float_count": float_count,
        "profiles": profiles,
        "bbox": bbox,
    }

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info(
        "map_radius_query_response",
        profile_count=payload["profile_count"],
        float_count=payload["float_count"],
        elapsed_ms=elapsed_ms,
    )
    return payload


@router.get("/floats/{platform_number}", response_model=FloatDetailResponse)
def get_float_detail(
    platform_number: str,
    db: Session = Depends(get_readonly_db),
) -> dict[str, Any]:
    """Return metadata and recent profile temperature/pressure data for one float."""
    start = time.perf_counter()
    settings = get_settings()

    log.info("map_float_detail_request", platform_number=platform_number)

    float_stmt = (
        select(
            Float.float_id,
            Float.platform_number,
            Float.wmo_id,
            Float.float_type,
            Float.deployment_date,
            Float.deployment_lat,
            Float.deployment_lon,
            Float.country,
            Float.program,
            mv_float_latest_position.c.timestamp.label("last_profile_date"),
            mv_float_latest_position.c.latitude.label("last_latitude"),
            mv_float_latest_position.c.longitude.label("last_longitude"),
        )
        .select_from(Float)
        .outerjoin(
            mv_float_latest_position,
            mv_float_latest_position.c.float_id == Float.float_id,
        )
        .where(Float.platform_number == platform_number)
    )
    float_row = db.execute(float_stmt).one_or_none()

    if float_row is None:
        raise HTTPException(status_code=404, detail=f"Float {platform_number} not found")

    stats_stmt = (
        select(
            func.count(Profile.profile_id).label("cycle_count"),
            func.min(Profile.timestamp).label("active_start"),
            func.max(Profile.timestamp).label("active_end"),
        )
        .where(Profile.platform_number == platform_number)
    )
    stats_row = db.execute(stats_stmt).one()

    recent_profile_ids_stmt = (
        select(Profile.profile_id, Profile.cycle_number, Profile.timestamp)
        .where(Profile.platform_number == platform_number)
        .order_by(Profile.timestamp.desc())
        .limit(settings.MAP_FLOAT_DETAIL_LAST_PROFILES)
    )
    recent_profile_rows = db.execute(recent_profile_ids_stmt).all()

    recent_profiles: list[dict[str, Any]] = []
    for profile_row in recent_profile_rows:
        levels_stmt = (
            select(Measurement.pressure, Measurement.temperature)
            .where(Measurement.profile_id == profile_row.profile_id)
            .order_by(Measurement.pressure.asc())
        )
        levels = db.execute(levels_stmt).all()

        pressure_levels = [float(l.pressure) for l in levels if l.pressure is not None]
        temperature_levels = [float(l.temperature) for l in levels if l.temperature is not None]

        recent_profiles.append(
            {
                "cycle_number": profile_row.cycle_number,
                "timestamp": _iso(profile_row.timestamp),
                "pressure_levels": pressure_levels,
                "temperature_levels": temperature_levels,
            }
        )

    payload = {
        "platform_number": float_row.platform_number,
        "wmo_id": float_row.wmo_id,
        "float_type": float_row.float_type,
        "deployment_date": _iso(float_row.deployment_date),
        "deployment_lat": float_row.deployment_lat,
        "deployment_lon": float_row.deployment_lon,
        "country": float_row.country,
        "program": float_row.program,
        "last_profile_date": _iso(float_row.last_profile_date),
        "last_latitude": float_row.last_latitude,
        "last_longitude": float_row.last_longitude,
        "cycle_count": int(stats_row.cycle_count or 0),
        "active_date_range_start": _iso(stats_row.active_start),
        "active_date_range_end": _iso(stats_row.active_end),
        "recent_profiles": recent_profiles,
    }

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info(
        "map_float_detail_response",
        platform_number=platform_number,
        cycle_count=payload["cycle_count"],
        recent_profiles=len(recent_profiles),
        elapsed_ms=elapsed_ms,
    )
    return payload


@router.get("/basin-floats", response_model=list[BasinFloatResponse])
def get_basin_floats(
    basin_name: str,
    db: Session = Depends(get_readonly_db),
) -> list[dict[str, Any]]:
    """Return latest float positions for a resolved ocean basin."""
    start = time.perf_counter()

    log.info("map_basin_floats_request", basin_name=basin_name)

    try:
        region = resolve_region_name(basin_name, db)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    stmt = (
        select(
            mv_float_latest_position.c.float_id,
            mv_float_latest_position.c.platform_number,
            Float.float_type,
            mv_float_latest_position.c.latitude,
            mv_float_latest_position.c.longitude,
            mv_float_latest_position.c.timestamp,
        )
        .select_from(
            mv_float_latest_position.join(
                Float,
                mv_float_latest_position.c.float_id == Float.float_id,
            )
        )
        .where(func.ST_Within(mv_float_latest_position.c.geom, region.geom))
        .order_by(mv_float_latest_position.c.platform_number.asc())
    )

    rows = db.execute(stmt).all()
    payload = [
        {
            "float_id": row.float_id,
            "platform_number": row.platform_number,
            "float_type": row.float_type,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "last_seen": _iso(row.timestamp),
        }
        for row in rows
    ]

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info(
        "map_basin_floats_response",
        input_name=basin_name,
        resolved_name=region.region_name,
        count=len(payload),
        elapsed_ms=elapsed_ms,
    )
    return payload


@router.get("/basin-polygons", response_model=BasinPolygonsResponse)
def get_basin_polygons(db: Session = Depends(get_readonly_db)) -> dict[str, Any]:
    """Return ocean basin polygons as GeoJSON FeatureCollection, cached in Redis."""
    start = time.perf_counter()
    cache_key = "map_basin_polygons"
    cache_ttl_seconds = 3600

    log.info("map_basin_polygons_request")

    redis_client = _get_redis_client()
    if redis_client:
        try:
            cached = redis_client.get(cache_key)
            if cached:
                data = json.loads(cached)
                log.info("map_basin_polygons_cache_hit", feature_count=len(data.get("features", [])))
                return data
        except Exception:
            log.warning("map_basin_polygons_cache_read_failed", exc_info=True)

    stmt = select(
        OceanRegion.region_id,
        OceanRegion.region_name,
        func.ST_AsGeoJSON(OceanRegion.geom).label("geojson"),
    ).order_by(OceanRegion.region_name.asc())

    rows = db.execute(stmt).all()
    features: list[dict[str, Any]] = []
    for row in rows:
        if not row.geojson:
            continue
        geometry = json.loads(row.geojson)
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "region_name": row.region_name,
                    "region_id": row.region_id,
                },
                "geometry": geometry,
            }
        )

    payload = {
        "type": "FeatureCollection",
        "features": features,
    }

    if redis_client:
        try:
            redis_client.set(cache_key, json.dumps(payload), ex=cache_ttl_seconds)
            log.info(
                "map_basin_polygons_cache_set",
                ttl_seconds=cache_ttl_seconds,
                feature_count=len(features),
            )
        except Exception:
            log.warning("map_basin_polygons_cache_write_failed", exc_info=True)

    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    log.info("map_basin_polygons_response", feature_count=len(features), elapsed_ms=elapsed_ms)
    return payload

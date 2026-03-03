/**
 * FloatChat — Map API Client (Feature 7)
 *
 * Typed async functions for all map backend API calls.
 * Follows the same pattern as `lib/api.ts`.
 */

import { ApiError } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_V1 = `${API_BASE}/api/v1`;

function getUserId(): string {
  if (typeof window === "undefined") return "";
  let uid = localStorage.getItem("floatchat_user_id");
  if (!uid) {
    uid = crypto.randomUUID();
    localStorage.setItem("floatchat_user_id", uid);
  }
  return uid;
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-User-ID": getUserId(),
    ...(options.headers as Record<string, string> | undefined),
  };

  const res = await fetch(`${API_V1}${path}`, {
    ...options,
    headers,
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, res.statusText, body);
  }

  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

export interface ActiveFloat {
  platform_number: string;
  float_type: string | null;
  latitude: number | null;
  longitude: number | null;
  last_seen: string | null;
}

export interface NearestFloat {
  float_id: number;
  platform_number: string;
  float_type: string | null;
  latitude: number | null;
  longitude: number | null;
  distance_km: number;
  last_seen: string | null;
}

export interface RadiusQueryRequest {
  lat: number;
  lon: number;
  radius_km: number;
  variables?: string[];
}

export interface RadiusQueryResult {
  profile_count: number;
  float_count: number;
  profiles: Array<Record<string, string | number | boolean | null>>;
  bbox: {
    type: "Polygon";
    coordinates: number[][][];
  } | null;
}

export interface RecentProfile {
  cycle_number: number;
  timestamp: string | null;
  pressure_levels: number[];
  temperature_levels: number[];
}

export interface FloatDetail {
  platform_number: string;
  wmo_id: string | null;
  float_type: string | null;
  deployment_date: string | null;
  deployment_lat: number | null;
  deployment_lon: number | null;
  country: string | null;
  program: string | null;
  last_profile_date: string | null;
  last_latitude: number | null;
  last_longitude: number | null;
  cycle_count: number;
  active_date_range_start: string | null;
  active_date_range_end: string | null;
  recent_profiles: RecentProfile[];
}

export interface BasinFloat {
  float_id: number;
  platform_number: string;
  float_type: string | null;
  latitude: number | null;
  longitude: number | null;
  last_seen: string | null;
}

export interface BasinPolygonFeature {
  type: "Feature";
  properties: {
    region_name: string;
    region_id: number;
  };
  geometry: GeoJSON.Geometry;
}

export interface BasinPolygonsResponse {
  type: "FeatureCollection";
  features: BasinPolygonFeature[];
}

export async function getActiveFloats(): Promise<ActiveFloat[]> {
  return apiFetch<ActiveFloat[]>("/map/active-floats");
}

export async function getNearestFloats(
  lat: number,
  lon: number,
  n?: number,
  maxDistanceKm?: number,
): Promise<NearestFloat[]> {
  const params = new URLSearchParams({
    lat: String(lat),
    lon: String(lon),
  });

  if (n !== undefined) {
    params.set("n", String(n));
  }
  if (maxDistanceKm !== undefined) {
    params.set("max_distance_km", String(maxDistanceKm));
  }

  return apiFetch<NearestFloat[]>(`/map/nearest-floats?${params.toString()}`);
}

export async function postRadiusQuery(
  lat: number,
  lon: number,
  radiusKm: number,
  variables?: string[],
): Promise<RadiusQueryResult> {
  const body: RadiusQueryRequest = {
    lat,
    lon,
    radius_km: radiusKm,
    ...(variables && variables.length > 0 ? { variables } : {}),
  };

  return apiFetch<RadiusQueryResult>("/map/radius-query", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function getFloatDetail(
  platformNumber: string,
): Promise<FloatDetail> {
  return apiFetch<FloatDetail>(`/map/floats/${encodeURIComponent(platformNumber)}`);
}

export async function getBasinFloats(
  basinName: string,
): Promise<BasinFloat[]> {
  const params = new URLSearchParams({ basin_name: basinName });
  return apiFetch<BasinFloat[]>(`/map/basin-floats?${params.toString()}`);
}

export async function getBasinPolygons(): Promise<BasinPolygonsResponse> {
  return apiFetch<BasinPolygonsResponse>("/map/basin-polygons");
}

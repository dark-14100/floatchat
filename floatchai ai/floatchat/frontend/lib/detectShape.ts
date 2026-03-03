// Shape detection heuristic for FloatChat visualization
// Determines which chart/map to render based on columns/rows

import type { ChartRow, ChartType, DetectedShape } from "../types/visualization";

/**
 * Detects the best visualization shape for a given result set.
 * @param columns - Column names from result_metadata
 * @param rows - Data rows (first 50 sampled)
 * @returns DetectedShape
 */
export function detectShape(columns: string[], rows: ChartRow[]): DetectedShape {
  const cols = columns.map((c) => c.toLowerCase());
  const has = (col: string) => cols.includes(col);
  const hasAny = (...candidates: string[]) => candidates.some(has);
  const isNumeric = (col: string) => {
    for (const row of rows.slice(0, 50)) {
      const val = row[col];
      if (val != null && typeof val === "number") return true;
    }
    return false;
  };

  // 1. Float trajectory map: lat/lon + time
  if (hasAny("latitude", "lat") && hasAny("longitude", "lon") && hasAny("juld", "timestamp", "date")) {
    return { primary: "float_trajectory_map" };
  }
  // 2. Float position map: lat/lon only
  if (hasAny("latitude", "lat") && hasAny("longitude", "lon")) {
    return { primary: "float_position_map" };
  }
  // 3. Salinity overlay: temp + salinity + depth/pressure
  if (hasAny("temperature", "temp") && hasAny("salinity", "psal") && hasAny("pressure", "depth")) {
    return { primary: "salinity_overlay", secondary: "ts_diagram" };
  }
  // 4. T-S diagram: temp + salinity
  if (hasAny("temperature", "temp") && hasAny("salinity", "psal")) {
    return { primary: "ts_diagram" };
  }
  // 5. Ocean profile: depth/pressure + any numeric
  if (hasAny("pressure", "depth")) {
    for (const col of cols) {
      if (["pressure", "depth"].includes(col)) continue;
      if (isNumeric(col)) return { primary: "ocean_profile" };
    }
  }
  // 6. Time series: date/time + any numeric
  if (hasAny("juld", "timestamp", "date")) {
    for (const col of cols) {
      if (["juld", "timestamp", "date"].includes(col)) continue;
      if (isNumeric(col)) return { primary: "time_series" };
    }
  }
  // 7. Fallback: no visualization
  return { primary: null };
}

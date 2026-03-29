export type AnomalySeverity = "low" | "medium" | "high";

export type AnomalyType =
  | "spatial_baseline"
  | "float_self_comparison"
  | "cluster_pattern"
  | "seasonal_baseline";

export interface AnomalyListItem {
  anomaly_id: string;
  float_id: number;
  profile_id: number;
  anomaly_type: AnomalyType;
  severity: AnomalySeverity;
  variable: string;
  baseline_value: number | null;
  observed_value: number | null;
  deviation_percent: number | null;
  description: string;
  detected_at: string;
  region: string | null;
  is_reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;
  platform_number: string;
  latitude: number | null;
  longitude: number | null;
}

export interface AnomalyListResponse {
  items: AnomalyListItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface AnomalyMeasurementRow {
  pressure: number | null;
  temperature: number | null;
  salinity: number | null;
  dissolved_oxygen: number | null;
  chlorophyll: number | null;
  nitrate: number | null;
  ph: number | null;
  bbp700: number | null;
  downwelling_irradiance: number | null;
}

export interface AnomalyDetail {
  anomaly_id: string;
  float_id: number;
  profile_id: number;
  anomaly_type: AnomalyType;
  severity: AnomalySeverity;
  variable: string;
  baseline_value: number | null;
  observed_value: number | null;
  deviation_percent: number | null;
  description: string;
  detected_at: string;
  region: string | null;
  is_reviewed: boolean;
  reviewed_by: string | null;
  reviewed_at: string | null;

  platform_number: string;
  float_type: string | null;
  deployment_date: string | null;
  deployment_lat: number | null;
  deployment_lon: number | null;
  country: string | null;
  program: string | null;

  profile_timestamp: string | null;
  profile_latitude: number | null;
  profile_longitude: number | null;
  measurements: AnomalyMeasurementRow[];

  baseline_comparison: {
    baseline_value: number | null;
    observed_value: number | null;
    deviation_percent: number | null;
  };
}

export interface AnomalyListParams {
  severity?: AnomalySeverity;
  anomaly_type?: AnomalyType;
  variable?: string;
  is_reviewed?: boolean;
  days?: number;
  limit?: number;
  offset?: number;
}

import { apiFetch } from "@/lib/api";
import type {
  AnomalyDetail,
  AnomalyListItem,
  AnomalyListParams,
  AnomalyListResponse,
} from "@/types/anomaly";

function buildQuery(params: AnomalyListParams): string {
  const qs = new URLSearchParams();

  if (params.severity) qs.set("severity", params.severity);
  if (params.anomaly_type) qs.set("anomaly_type", params.anomaly_type);
  if (params.variable) qs.set("variable", params.variable);
  if (params.is_reviewed !== undefined) qs.set("is_reviewed", String(params.is_reviewed));
  if (params.days !== undefined) qs.set("days", String(params.days));
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));

  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export async function getAnomalies(params: AnomalyListParams = {}): Promise<AnomalyListResponse> {
  return apiFetch<AnomalyListResponse>(`/anomalies${buildQuery(params)}`);
}

export async function getAnomalyDetail(anomalyId: string): Promise<AnomalyDetail> {
  return apiFetch<AnomalyDetail>(`/anomalies/${encodeURIComponent(anomalyId)}`);
}

export async function markAnomalyReviewed(anomalyId: string): Promise<AnomalyListItem> {
  return apiFetch<AnomalyListItem>(`/anomalies/${encodeURIComponent(anomalyId)}/review`, {
    method: "PATCH",
  });
}

export async function getUnreviewedAnomalyCount(days = 7): Promise<number> {
  const response = await getAnomalies({ is_reviewed: false, days, limit: 1, offset: 0 });
  return response.total;
}

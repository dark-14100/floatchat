import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_V1 = `${API_BASE}/api/v1`;

export type AdminIngestionStatus = "pending" | "running" | "succeeded" | "failed";
export type AdminIngestionSource = "manual_upload" | "gdac_sync";
export type GDACSyncStatus = "running" | "completed" | "failed" | "partial";
export type GDACSyncTriggeredBy = "scheduled" | "manual";

export interface AdminDataset {
  dataset_id: number;
  name: string | null;
  description: string | null;
  source_filename: string | null;
  raw_file_path: string | null;
  ingestion_date: string | null;
  date_range_start: string | null;
  date_range_end: string | null;
  float_count: number | null;
  profile_count: number | null;
  variable_list: unknown;
  summary_text: string | null;
  is_active: boolean;
  is_public: boolean;
  tags: unknown;
  dataset_version: number;
  created_at: string | null;
  deleted_at: string | null;
  deleted_by: string | null;
  ingestion_job_count?: number;
  latest_job_status?: AdminIngestionStatus | null;
}

export interface AdminIngestionJob {
  job_id: string;
  dataset_id: number | null;
  dataset_name?: string | null;
  source: AdminIngestionSource;
  original_filename: string | null;
  raw_file_path: string | null;
  status: AdminIngestionStatus;
  progress_pct: number;
  profiles_total: number | null;
  profiles_ingested: number;
  error_log: string | null;
  errors: unknown;
  started_at: string | null;
  completed_at: string | null;
  created_at: string | null;
}

export interface GDACSyncRun {
  run_id: string;
  started_at: string | null;
  completed_at: string | null;
  status: GDACSyncStatus;
  index_profiles_found: number | null;
  profiles_downloaded: number | null;
  profiles_ingested: number | null;
  profiles_skipped: number | null;
  error_message: string | null;
  gdac_mirror: string;
  lookback_days: number;
  triggered_by: GDACSyncTriggeredBy;
  duration_seconds: number | null;
}

export interface AdminDatasetDetail extends AdminDataset {
  measurement_count: number;
  ingestion_job_history: AdminIngestionJob[];
  storage_size_bytes: number;
}

export interface AdminDatasetsResponse {
  datasets: AdminDataset[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminIngestionJobsResponse {
  jobs: AdminIngestionJob[];
  total: number;
  limit: number;
  offset: number;
}

export interface GDACSyncRunsResponse {
  runs: GDACSyncRun[];
  total: number;
  limit: number;
  offset: number;
}

export interface AdminAuditLogItem {
  log_id: string;
  admin_user_id: string | null;
  admin_user_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string;
  details: unknown;
  created_at: string | null;
}

export interface AdminAuditLogResponse {
  logs: AdminAuditLogItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface TaskQueuedResponse {
  task_id: string;
  status: "queued";
}

export interface RetryIngestionResponse {
  job_id: string;
  dataset_id: number;
  status: "pending";
  message: string;
}

export interface UploadAcceptedResponse {
  job_id: string;
  dataset_id: number;
  status: "pending";
  message: string;
}

export interface GDACSyncTriggerResponse {
  run_id: string;
  status: "queued";
}

export interface ListAdminDatasetsParams {
  include_deleted?: boolean;
  is_public?: boolean;
  tags?: string;
  limit?: number;
  offset?: number;
}

export interface ListAdminIngestionJobsParams {
  status?: AdminIngestionStatus;
  source?: AdminIngestionSource;
  dataset_id?: number;
  days?: number;
  limit?: number;
  offset?: number;
}

export interface ListAdminAuditLogParams {
  admin_user_id?: string;
  action?: string;
  entity_type?: string;
  days?: number;
  limit?: number;
  offset?: number;
}

export interface ListGDACSyncRunsParams {
  status?: GDACSyncStatus;
  days?: number;
  limit?: number;
  offset?: number;
}

export interface AdminDatasetMetadataPatch {
  name?: string;
  description?: string;
  tags?: string[];
  is_public?: boolean;
}

export interface HardDeleteRequest {
  confirm: boolean;
  confirm_dataset_name: string;
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export async function listAdminDatasets(
  params: ListAdminDatasetsParams = {},
): Promise<AdminDatasetsResponse> {
  const query = buildQuery({
    include_deleted: params.include_deleted,
    is_public: params.is_public,
    tags: params.tags,
    limit: params.limit,
    offset: params.offset,
  });
  return apiFetch<AdminDatasetsResponse>(`/admin/datasets${query}`);
}

export async function getAdminDatasetDetail(datasetId: number): Promise<AdminDatasetDetail> {
  return apiFetch<AdminDatasetDetail>(`/admin/datasets/${datasetId}`);
}

export async function patchAdminDatasetMetadata(
  datasetId: number,
  patch: AdminDatasetMetadataPatch,
): Promise<AdminDataset> {
  return apiFetch<AdminDataset>(`/admin/datasets/${datasetId}/metadata`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export async function regenerateAdminDatasetSummary(
  datasetId: number,
): Promise<TaskQueuedResponse> {
  return apiFetch<TaskQueuedResponse>(`/admin/datasets/${datasetId}/regenerate-summary`, {
    method: "POST",
  });
}

export async function softDeleteAdminDataset(datasetId: number): Promise<AdminDataset> {
  return apiFetch<AdminDataset>(`/admin/datasets/${datasetId}/soft-delete`, {
    method: "POST",
  });
}

export async function restoreAdminDataset(datasetId: number): Promise<AdminDataset> {
  return apiFetch<AdminDataset>(`/admin/datasets/${datasetId}/restore`, {
    method: "POST",
  });
}

export async function hardDeleteAdminDataset(
  datasetId: number,
  payload: HardDeleteRequest,
): Promise<TaskQueuedResponse> {
  return apiFetch<TaskQueuedResponse>(`/admin/datasets/${datasetId}/hard-delete`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function listAdminIngestionJobs(
  params: ListAdminIngestionJobsParams = {},
): Promise<AdminIngestionJobsResponse> {
  const query = buildQuery({
    status: params.status,
    source: params.source,
    dataset_id: params.dataset_id,
    days: params.days,
    limit: params.limit,
    offset: params.offset,
  });
  return apiFetch<AdminIngestionJobsResponse>(`/admin/ingestion-jobs${query}`);
}

export async function retryAdminIngestionJob(jobId: string): Promise<RetryIngestionResponse> {
  return apiFetch<RetryIngestionResponse>(`/admin/ingestion-jobs/${encodeURIComponent(jobId)}/retry`, {
    method: "POST",
  });
}

export async function listAdminAuditLog(
  params: ListAdminAuditLogParams = {},
): Promise<AdminAuditLogResponse> {
  const query = buildQuery({
    admin_user_id: params.admin_user_id,
    action: params.action,
    entity_type: params.entity_type,
    days: params.days,
    limit: params.limit,
    offset: params.offset,
  });
  return apiFetch<AdminAuditLogResponse>(`/admin/audit-log${query}`);
}

export async function triggerGDACSync(): Promise<GDACSyncTriggerResponse> {
  return apiFetch<GDACSyncTriggerResponse>("/admin/gdac-sync/trigger", {
    method: "POST",
  });
}

export async function listGDACSyncRuns(
  params: ListGDACSyncRunsParams = {},
): Promise<GDACSyncRunsResponse> {
  const query = buildQuery({
    status: params.status,
    days: params.days,
    limit: params.limit,
    offset: params.offset,
  });
  return apiFetch<GDACSyncRunsResponse>(`/admin/gdac-sync/runs${query}`);
}

export async function getGDACSyncRunDetail(runId: string): Promise<GDACSyncRun> {
  return apiFetch<GDACSyncRun>(`/admin/gdac-sync/runs/${encodeURIComponent(runId)}`);
}

export async function uploadDatasetFile(
  file: File,
  datasetName: string | undefined,
  onProgress?: (percent: number) => void,
): Promise<UploadAcceptedResponse> {
  const token = useAuthStore.getState().accessToken;

  return new Promise<UploadAcceptedResponse>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_V1}/datasets/upload`);
    xhr.withCredentials = true;

    if (token) {
      xhr.setRequestHeader("Authorization", `Bearer ${token}`);
    }

    xhr.upload.onprogress = (evt: ProgressEvent<EventTarget>) => {
      if (!onProgress || !evt.lengthComputable) {
        return;
      }
      const percent = Math.round((evt.loaded / evt.total) * 100);
      onProgress(Math.max(0, Math.min(100, percent)));
    };

    xhr.onerror = () => {
      reject(new Error("Upload failed. Please try again."));
    };

    xhr.onreadystatechange = () => {
      if (xhr.readyState !== XMLHttpRequest.DONE) {
        return;
      }

      const body = xhr.responseText || "";
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const parsed = JSON.parse(body) as UploadAcceptedResponse;
          resolve(parsed);
        } catch {
          reject(new Error("Upload succeeded but response parsing failed."));
        }
        return;
      }

      let detail = "Upload request failed.";
      try {
        const parsed = JSON.parse(body) as { detail?: string };
        if (typeof parsed.detail === "string") {
          detail = parsed.detail;
        }
      } catch {
        if (body) {
          detail = body;
        }
      }

      reject(new Error(detail));
    };

    const formData = new FormData();
    formData.append("file", file);
    if (datasetName && datasetName.trim()) {
      formData.append("dataset_name", datasetName.trim());
    }

    xhr.send(formData);
  });
}

interface SSEParseState {
  buffer: string;
  currentEvent: string | null;
}

function parseSSEChunk(
  state: SSEParseState,
  chunk: string,
  onEvent: (eventType: string, data: unknown) => void,
): void {
  state.buffer += chunk;
  const lines = state.buffer.split("\n");
  state.buffer = lines.pop() ?? "";

  for (const rawLine of lines) {
    const line = rawLine.trim();
    if (line.startsWith("event:")) {
      state.currentEvent = line.slice(6).trim();
      continue;
    }
    if (line.startsWith("data:")) {
      const dataRaw = line.slice(5).trim();
      if (!state.currentEvent) {
        continue;
      }
      try {
        const parsed = JSON.parse(dataRaw);
        onEvent(state.currentEvent, parsed);
      } catch {
        // Ignore malformed chunks.
      }
      state.currentEvent = null;
    }
  }
}

export interface AdminIngestionStreamPayload {
  job_id: string;
  dataset_id: number | null;
  dataset_name: string | null;
  source: AdminIngestionSource;
  status: AdminIngestionStatus;
  progress_pct: number;
  profiles_ingested: number;
  error_message: string | null;
  updated_at: string | null;
}

export interface AdminIngestionStreamCallbacks {
  onJobUpdate: (payload: AdminIngestionStreamPayload) => void;
  onHeartbeat?: () => void;
  onError: (error: Error) => void;
}

export function createAdminIngestionStream(
  callbacks: AdminIngestionStreamCallbacks,
): AbortController {
  const controller = new AbortController();

  const run = async () => {
    try {
      const token = useAuthStore.getState().accessToken;
      const headers: Record<string, string> = {};
      if (token) {
        headers.Authorization = `Bearer ${token}`;
      }

      const response = await fetch(`${API_V1}/admin/ingestion-jobs/stream`, {
        method: "GET",
        credentials: "include",
        headers,
        signal: controller.signal,
      });

      if (!response.ok) {
        const body = await response.text().catch(() => "");
        throw new Error(`Ingestion stream failed: ${response.status} ${body}`);
      }

      if (!response.body) {
        throw new Error("Ingestion stream body is unavailable.");
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const state: SSEParseState = { buffer: "", currentEvent: null };

      let done = false;
      while (!done) {
        const packet = await reader.read();
        done = packet.done;

        if (packet.value) {
          const text = decoder.decode(packet.value, { stream: !done });
          parseSSEChunk(state, text, (eventType, data) => {
            if (eventType === "job_update") {
              callbacks.onJobUpdate(data as AdminIngestionStreamPayload);
              return;
            }
            if (eventType === "heartbeat") {
              callbacks.onHeartbeat?.();
              return;
            }
            if (eventType === "error") {
              const msg =
                typeof data === "object" && data !== null && "error" in data
                  ? String((data as { error: unknown }).error)
                  : "stream_error";
              callbacks.onError(new Error(msg));
            }
          });
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      callbacks.onError(err instanceof Error ? err : new Error(String(err)));
    }
  };

  void run();
  return controller;
}

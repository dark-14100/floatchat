import type { ChartRow } from "@/types/visualization";

export type ExportFormat = "csv" | "netcdf" | "json";

export type ExportTaskStatus = "queued" | "processing" | "complete" | "failed";

export interface ExportFilters {
  variables?: string[];
  min_pressure?: number;
  max_pressure?: number;
}

export interface CreateExportRequest {
  message_id: string;
  format: ExportFormat;
  rows: ChartRow[];
  filters?: ExportFilters;
}

export interface ExportQueuedResponse {
  task_id: string;
  status: "queued";
  poll_url: string;
}

export interface ExportStatusResponse {
  status: ExportTaskStatus;
  task_id: string;
  download_url?: string;
  expires_at?: string;
  error?: string;
}

export interface ExportErrorResponse {
  error: string;
  detail: string;
}

export interface CreateExportSyncResponse {
  mode: "sync";
  blob: Blob;
  filename: string;
  contentType: string;
}

export interface CreateExportAsyncResponse {
  mode: "async";
  queued: ExportQueuedResponse;
}

export type CreateExportResponse =
  | CreateExportSyncResponse
  | CreateExportAsyncResponse;

import { ApiError, apiFetch } from "@/lib/api";
import { useAuthStore } from "@/store/authStore";
import type { RefreshResponse } from "@/types/auth";
import type {
  CreateExportRequest,
  CreateExportResponse,
  ExportFormat,
  ExportQueuedResponse,
  ExportStatusResponse,
} from "@/types/export";

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_V1 = `${API_BASE}/api/v1`;

function fallbackFilename(format: ExportFormat): string {
  const extension = format === "netcdf" ? "nc" : format;
  const isoSafe = new Date().toISOString().replace(/[.:]/g, "-");
  return `floatchat_export_${isoSafe}.${extension}`;
}

function extractFilename(
  contentDisposition: string | null,
  format: ExportFormat,
): string {
  if (!contentDisposition) {
    return fallbackFilename(format);
  }

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match?.[1]) {
    try {
      return decodeURIComponent(utf8Match[1]);
    } catch {
      return utf8Match[1];
    }
  }

  const basicMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (basicMatch?.[1]) {
    return basicMatch[1];
  }

  return fallbackFilename(format);
}

function isQueuedResponse(value: unknown): value is ExportQueuedResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.task_id === "string" &&
    candidate.status === "queued" &&
    typeof candidate.poll_url === "string"
  );
}

async function refreshAccessToken(): Promise<string | null> {
  try {
    const response = await fetch(`${API_V1}/auth/refresh`, {
      method: "POST",
      credentials: "include",
      headers: {
        "Content-Type": "application/json",
      },
    });

    if (!response.ok) {
      return null;
    }

    const payload = (await response.json()) as RefreshResponse;
    useAuthStore.getState().setAuth(payload.user, payload.access_token);
    return payload.access_token;
  } catch {
    return null;
  }
}

async function exportFetch(
  path: string,
  options: RequestInit,
  hasRetried = false,
): Promise<Response> {
  const headers = new Headers(options.headers);
  const accessToken = useAuthStore.getState().accessToken;

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  if (!headers.has("Content-Type") && options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_V1}${path}`, {
    ...options,
    headers,
    credentials: options.credentials ?? "include",
  });

  if (response.status === 401 && !hasRetried) {
    const refreshedToken = await refreshAccessToken();
    if (refreshedToken) {
      return exportFetch(path, options, true);
    }
    useAuthStore.getState().clearAuth();
  }

  return response;
}

async function throwApiError(response: Response): Promise<never> {
  const body = await response.text().catch(() => "");
  throw new ApiError(response.status, response.statusText, body);
}

export async function createExport(
  request: CreateExportRequest,
): Promise<CreateExportResponse> {
  const response = await exportFetch("/export", {
    method: "POST",
    body: JSON.stringify(request),
  });

  if (!response.ok) {
    await throwApiError(response);
  }

  const contentDisposition = response.headers.get("Content-Disposition");
  const contentType = response.headers.get("Content-Type") ?? "application/octet-stream";

  if (contentDisposition) {
    const blob = await response.blob();
    return {
      mode: "sync",
      blob,
      filename: extractFilename(contentDisposition, request.format),
      contentType,
    };
  }

  if (!contentType.includes("application/json")) {
    const blob = await response.blob();
    return {
      mode: "sync",
      blob,
      filename: fallbackFilename(request.format),
      contentType,
    };
  }

  const bodyText = await response.text();

  try {
    const parsed: unknown = JSON.parse(bodyText);
    if (isQueuedResponse(parsed)) {
      return {
        mode: "async",
        queued: parsed,
      };
    }
  } catch {
    // Fall through to sync blob conversion.
  }

  return {
    mode: "sync",
    blob: new Blob([bodyText], { type: contentType }),
    filename: fallbackFilename(request.format),
    contentType,
  };
}

export async function getExportStatus(
  taskId: string,
): Promise<ExportStatusResponse> {
  return apiFetch<ExportStatusResponse>(`/export/status/${encodeURIComponent(taskId)}`);
}

export function downloadExportBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

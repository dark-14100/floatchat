/**
 * FloatChat — API Client
 *
 * Typed async functions for all backend API calls.
 * Uses bearer access token from in-memory auth store.
 * On 401, attempts one silent refresh and retries once.
 * All throw typed errors on HTTP failures.
 */

import type {
  ChatSession,
  ChatMessage,
  CreateSessionResponse,
  Suggestion,
} from "@/types/chat";
import type { RefreshResponse } from "@/types/auth";
import { useAuthStore } from "@/store/authStore";

// ── Configuration ──────────────────────────────────────────────────────────

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_V1 = `${API_BASE}/api/v1`;

export interface ApiFetchOptions extends RequestInit {
  includeLegacyUserId?: boolean;
  retryOnAuthError?: boolean;
  skipAuthRedirect?: boolean;
}

// ── Error class ────────────────────────────────────────────────────────────

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly statusText: string,
    public readonly body: string,
  ) {
    super(`API ${status}: ${statusText}`);
    this.name = "ApiError";
  }
}

// ── User ID helper ─────────────────────────────────────────────────────────

export function getLegacyUserId(): string {
  if (typeof window === "undefined") return "";
  let uid = localStorage.getItem("floatchat_user_id");
  if (!uid) {
    uid = crypto.randomUUID();
    localStorage.setItem("floatchat_user_id", uid);
  }
  return uid;
}

function redirectToLogin(): void {
  if (typeof window === "undefined") return;

  const { pathname, search } = window.location;
  const isAuthRoute =
    pathname === "/login" ||
    pathname === "/signup" ||
    pathname === "/forgot-password" ||
    pathname === "/reset-password";

  if (isAuthRoute) {
    return;
  }

  const redirectTarget = `${pathname}${search}`;
  window.location.href = `/login?redirect=${encodeURIComponent(redirectTarget)}`;
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

async function handleUnauthorized(skipAuthRedirect: boolean): Promise<void> {
  useAuthStore.getState().clearAuth();
  if (!skipAuthRedirect) {
    redirectToLogin();
  }
}

// ── Base fetch wrapper ─────────────────────────────────────────────────────

export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
  hasRetried = false,
): Promise<T> {
  const {
    includeLegacyUserId = false,
    retryOnAuthError = true,
    skipAuthRedirect = false,
    ...requestInit
  } = options;

  const headers = new Headers(requestInit.headers);
  const accessToken = useAuthStore.getState().accessToken;

  if (!headers.has("Content-Type") && requestInit.body && !(requestInit.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  if (accessToken) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }

  if (includeLegacyUserId) {
    const legacyUserId = getLegacyUserId();
    if (legacyUserId) {
      headers.set("X-User-ID", legacyUserId);
    }
  }

  const res = await fetch(`${API_V1}${path}`, {
    ...requestInit,
    headers,
    credentials: requestInit.credentials ?? "include",
  });

  if (res.status === 401) {
    if (retryOnAuthError && !hasRetried) {
      const refreshedToken = await refreshAccessToken();
      if (refreshedToken) {
        return apiFetch<T>(path, options, true);
      }
    }

    await handleUnauthorized(skipAuthRedirect);
  }

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new ApiError(res.status, res.statusText, body);
  }

  // 204 No Content — return undefined cast as T
  if (res.status === 204) {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

// ── Session endpoints ──────────────────────────────────────────────────────

export async function createSession(
  name?: string,
): Promise<CreateSessionResponse> {
  return apiFetch<CreateSessionResponse>("/chat/sessions", {
    method: "POST",
    body: JSON.stringify(name ? { name } : {}),
  });
}

export async function listSessions(): Promise<ChatSession[]> {
  return apiFetch<ChatSession[]>("/chat/sessions");
}

export async function getSession(sessionId: string): Promise<ChatSession> {
  return apiFetch<ChatSession>(`/chat/sessions/${sessionId}`);
}

export async function renameSession(
  sessionId: string,
  name: string,
): Promise<void> {
  await apiFetch<ChatSession>(`/chat/sessions/${sessionId}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export async function deleteSession(sessionId: string): Promise<void> {
  await apiFetch<void>(`/chat/sessions/${sessionId}`, {
    method: "DELETE",
  });
}

// ── Message endpoints ──────────────────────────────────────────────────────

export async function getMessages(
  sessionId: string,
  limit?: number,
  beforeId?: string,
): Promise<ChatMessage[]> {
  const params = new URLSearchParams();
  if (limit !== undefined) params.set("limit", String(limit));
  if (beforeId) params.set("before_message_id", beforeId);
  const qs = params.toString();
  const path = `/chat/sessions/${sessionId}/messages${qs ? `?${qs}` : ""}`;
  return apiFetch<ChatMessage[]>(path);
}

// ── Suggestions endpoint ───────────────────────────────────────────────────

export async function getLoadTimeSuggestions(): Promise<Suggestion[]> {
  const res = await apiFetch<{ suggestions: Suggestion[] }>(
    "/chat/suggestions",
  );
  return res.suggestions;
}

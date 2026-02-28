/**
 * FloatChat — API Client
 *
 * Typed async functions for all backend API calls.
 * All functions send the X-User-ID header from localStorage.
 * All throw typed errors on HTTP failures.
 */

import type {
  ChatSession,
  ChatMessage,
  CreateSessionResponse,
  Suggestion,
} from "@/types/chat";

// ── Configuration ──────────────────────────────────────────────────────────

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_V1 = `${API_BASE}/api/v1`;

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

function getUserId(): string {
  if (typeof window === "undefined") return "";
  let uid = localStorage.getItem("floatchat_user_id");
  if (!uid) {
    uid = crypto.randomUUID();
    localStorage.setItem("floatchat_user_id", uid);
  }
  return uid;
}

// ── Base fetch wrapper ─────────────────────────────────────────────────────

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

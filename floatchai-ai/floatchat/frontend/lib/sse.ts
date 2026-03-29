/**
 * FloatChat — SSE Client
 *
 * Creates an SSE connection to the backend query endpoint using
 * fetch + ReadableStream (not EventSource, which only supports GET).
 *
 * Handles chunked SSE data correctly — a single chunk may contain
 * multiple events, or a single event may span multiple chunks.
 */

import type { SSEEvent } from "@/types/chat";

// ── Configuration ──────────────────────────────────────────────────────────

const API_BASE =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

const API_V1 = `${API_BASE}/api/v1`;

// ── User ID helper (same as api.ts) ────────────────────────────────────────

function getUserId(): string {
  if (typeof window === "undefined") return "";
  let uid = localStorage.getItem("floatchat_user_id");
  if (!uid) {
    uid = crypto.randomUUID();
    localStorage.setItem("floatchat_user_id", uid);
  }
  return uid;
}

// ── SSE line parser ────────────────────────────────────────────────────────

interface SSEParseState {
  buffer: string;
  currentEvent: string | null;
}

function parseSSEChunk(
  state: SSEParseState,
  chunk: string,
  onEvent: (event: SSEEvent) => void,
): void {
  state.buffer += chunk;

  // Process complete lines (terminated by \n)
  const lines = state.buffer.split("\n");
  // Keep the last incomplete line in the buffer
  state.buffer = lines.pop() ?? "";

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith("event:")) {
      state.currentEvent = trimmed.slice(6).trim();
    } else if (trimmed.startsWith("data:")) {
      const dataStr = trimmed.slice(5).trim();
      if (state.currentEvent && dataStr) {
        try {
          const data: unknown = JSON.parse(dataStr);
          onEvent({
            type: state.currentEvent,
            data,
          } as SSEEvent);
        } catch {
          // Skip malformed JSON — Hard Rule 9 says backend always sends valid JSON
        }
      }
      state.currentEvent = null;
    }
    // Ignore empty lines and other fields (id:, retry:, comments)
  }
}

// ── Stream creator ─────────────────────────────────────────────────────────

export interface QueryStreamCallbacks {
  onEvent: (event: SSEEvent) => void;
  onError: (error: Error) => void;
  onDone: () => void;
}

/**
 * Open an SSE stream to the query endpoint.
 *
 * @returns AbortController — call `.abort()` to cancel the stream.
 */
export function createQueryStream(
  sessionId: string,
  query: string,
  confirm: boolean,
  callbacks: QueryStreamCallbacks,
): AbortController {
  const controller = new AbortController();

  const run = async () => {
    try {
      const res = await fetch(
        `${API_V1}/chat/sessions/${sessionId}/query`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-User-ID": getUserId(),
          },
          body: JSON.stringify({ query, confirm }),
          signal: controller.signal,
        },
      );

      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`SSE request failed: ${res.status} ${body}`);
      }

      if (!res.body) {
        throw new Error("Response body is null — streaming not supported");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const state: SSEParseState = { buffer: "", currentEvent: null };

      let done = false;
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;

        if (value) {
          const text = decoder.decode(value, { stream: !done });
          parseSSEChunk(state, text, (event) => {
            callbacks.onEvent(event);
            if (event.type === "done") {
              callbacks.onDone();
            }
          });
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        // Stream was intentionally cancelled — not an error
        return;
      }
      callbacks.onError(
        err instanceof Error ? err : new Error(String(err)),
      );
    }
  };

  run();

  return controller;
}

// ── Confirmation stream ────────────────────────────────────────────────────

/**
 * Open an SSE stream to the confirmation endpoint.
 *
 * @returns AbortController — call `.abort()` to cancel the stream.
 */
export function createConfirmStream(
  sessionId: string,
  messageId: string,
  callbacks: QueryStreamCallbacks,
): AbortController {
  const controller = new AbortController();

  const run = async () => {
    try {
      const res = await fetch(
        `${API_V1}/chat/sessions/${sessionId}/query/confirm`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-User-ID": getUserId(),
          },
          body: JSON.stringify({ message_id: messageId }),
          signal: controller.signal,
        },
      );

      if (!res.ok) {
        const body = await res.text().catch(() => "");
        throw new Error(`Confirm request failed: ${res.status} ${body}`);
      }

      if (!res.body) {
        throw new Error("Response body is null — streaming not supported");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      const state: SSEParseState = { buffer: "", currentEvent: null };

      let done = false;
      while (!done) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;

        if (value) {
          const text = decoder.decode(value, { stream: !done });
          parseSSEChunk(state, text, (event) => {
            callbacks.onEvent(event);
            if (event.type === "done") {
              callbacks.onDone();
            }
          });
        }
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      callbacks.onError(
        err instanceof Error ? err : new Error(String(err)),
      );
    }
  };

  run();

  return controller;
}

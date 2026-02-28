/**
 * FloatChat — Chat Interface TypeScript Types
 *
 * All API response shapes and SSE event discriminated union.
 * No `any` types — Hard Rule 5.
 */

// ── Chat Session ───────────────────────────────────────────────────────────

export interface ChatSession {
  session_id: string;
  name: string | null;
  message_count: number;
  created_at: string;
  last_active_at: string;
  is_active: boolean;
}

export interface CreateSessionResponse {
  session_id: string;
  created_at: string;
}

// ── Chat Message ───────────────────────────────────────────────────────────

export interface ResultMetadata {
  columns: string[];
  row_count: number;
  truncated: boolean;
  execution_time_ms: number;
  attempt_count: number;
}

export interface MessageError {
  error: string;
  error_type: string;
}

export interface ChatMessage {
  message_id: string;
  session_id: string;
  role: "user" | "assistant";
  content: string;
  nl_query: string | null;
  generated_sql: string | null;
  result_metadata: ResultMetadata | null;
  follow_up_suggestions: string[] | null;
  error: MessageError | null;
  status: "pending_confirmation" | "confirmed" | "completed" | "error" | null;
  created_at: string;
}

// ── Result Data (from SSE results event) ───────────────────────────────────

export interface ResultData {
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  row_count: number;
  truncated: boolean;
  sql: string;
  interpretation: string;
  execution_time_ms: number;
  attempt_count: number;
}

// ── Suggestions ────────────────────────────────────────────────────────────

export interface Suggestion {
  query: string;
  description: string;
}

export type FollowUpSuggestion = string;

// ── SSE Events (discriminated union) ───────────────────────────────────────

export interface SSEThinkingEvent {
  type: "thinking";
  data: { status: string };
}

export interface SSEInterpretingEvent {
  type: "interpreting";
  data: {
    interpretation: string;
    sql: string;
  };
}

export interface SSEExecutingEvent {
  type: "executing";
  data: { status: string };
}

export interface SSEResultsEvent {
  type: "results";
  data: ResultData;
}

export interface SSESuggestionsEvent {
  type: "suggestions";
  data: { suggestions: FollowUpSuggestion[] };
}

export interface SSEAwaitingConfirmationEvent {
  type: "awaiting_confirmation";
  data: {
    message_id: string;
    estimated_rows: number;
    sql: string;
    interpretation: string;
  };
}

export interface SSEErrorEvent {
  type: "error";
  data: {
    error: string;
    error_type: string;
  };
}

export interface SSEDoneEvent {
  type: "done";
  data: { status: string };
}

export type SSEEvent =
  | SSEThinkingEvent
  | SSEInterpretingEvent
  | SSEExecutingEvent
  | SSEResultsEvent
  | SSESuggestionsEvent
  | SSEAwaitingConfirmationEvent
  | SSEErrorEvent
  | SSEDoneEvent;

// ── Stream state for UI ────────────────────────────────────────────────────

export type StreamState =
  | "thinking"
  | "interpreting"
  | "executing"
  | "done"
  | null;

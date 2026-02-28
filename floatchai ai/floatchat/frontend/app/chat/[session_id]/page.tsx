"use client";

/**
 * /chat/[session_id] — Main chat view.
 *
 * Composes ChatThread + ChatInput.
 * Handles:
 * - SSE query streaming → store actions
 * - Confirmation flow (Run this query / Cancel)
 * - Retry / Try again
 * - Follow-up + suggestion selection → auto-submit
 * - Cleanup on unmount (abort stream)
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef } from "react";
import { useChatStore } from "@/store/chatStore";
import { createQueryStream, createConfirmStream } from "@/lib/sse";
import type {
  ChatMessage,
  SSEEvent,
  SSEInterpretingEvent,
  SSEResultsEvent,
  SSESuggestionsEvent,
  SSEAwaitingConfirmationEvent,
  SSEErrorEvent,
} from "@/types/chat";
import ChatThread from "@/components/chat/ChatThread";
import ChatInput, { type ChatInputHandle } from "@/components/chat/ChatInput";

// ── Helpers ────────────────────────────────────────────────────────────────

function uuid(): string {
  return crypto.randomUUID();
}

// ── Component ──────────────────────────────────────────────────────────────

export default function ChatSessionPage() {
  const params = useParams<{ session_id: string }>();
  const sessionId = params.session_id;

  // Store selectors
  const setActiveSession = useChatStore((s) => s.setActiveSession);
  const appendMessage = useChatStore((s) => s.appendMessage);
  const updateLastMessage = useChatStore((s) => s.updateLastMessage);
  const setLoading = useChatStore((s) => s.setLoading);
  const setStreamState = useChatStore((s) => s.setStreamState);
  const setPendingInterpretation = useChatStore(
    (s) => s.setPendingInterpretation,
  );
  const isLoading = useChatStore((s) => s.isLoading);
  const streamState = useChatStore((s) => s.streamState);
  const pendingInterpretation = useChatStore((s) => s.pendingInterpretation);

  // Refs
  const abortRef = useRef<AbortController | null>(null);
  const inputRef = useRef<ChatInputHandle>(null);

  // Track the current streaming result data so we can build the final message
  const streamDataRef = useRef<{
    interpretation: string;
    sql: string;
    rows: Record<string, string | number | boolean | null>[];
    columns: string[];
    rowCount: number;
    truncated: boolean;
    executionTimeMs: number;
    attemptCount: number;
    followUps: string[];
    resultContent: string;
  } | null>(null);

  // ── Set active session on mount ─────────
  useEffect(() => {
    setActiveSession(sessionId);
  }, [sessionId, setActiveSession]);

  // ── Cleanup on unmount ──────────────────
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  // ── SSE event handler ──────────────────────────────────────────────────

  const handleSSEEvent = useCallback(
    (event: SSEEvent) => {
      switch (event.type) {
        case "thinking":
          setStreamState("thinking");
          break;

        case "interpreting": {
          const interp = event as SSEInterpretingEvent;
          setStreamState("interpreting");
          setPendingInterpretation(interp.data.interpretation);
          if (streamDataRef.current) {
            streamDataRef.current.interpretation = interp.data.interpretation;
            streamDataRef.current.sql = interp.data.sql;
          }
          break;
        }

        case "executing":
          setStreamState("executing");
          break;

        case "results": {
          const results = (event as SSEResultsEvent).data;
          if (streamDataRef.current) {
            streamDataRef.current.rows = results.rows;
            streamDataRef.current.columns = results.columns;
            streamDataRef.current.rowCount = results.row_count;
            streamDataRef.current.truncated = results.truncated;
            streamDataRef.current.executionTimeMs = results.execution_time_ms;
            streamDataRef.current.attemptCount = results.attempt_count;
            streamDataRef.current.resultContent = results.interpretation;
            streamDataRef.current.sql = results.sql;
          }

          // Build the assistant message from results
          const assistantMsg: ChatMessage = {
            message_id: uuid(),
            session_id: sessionId,
            role: "assistant",
            content: results.interpretation,
            nl_query: null,
            generated_sql: results.sql,
            result_metadata: {
              columns: results.columns,
              row_count: results.row_count,
              truncated: results.truncated,
              execution_time_ms: results.execution_time_ms,
              attempt_count: results.attempt_count,
            },
            follow_up_suggestions: null,
            error: null,
            status: "completed",
            created_at: new Date().toISOString(),
          };
          appendMessage(sessionId, assistantMsg);
          setStreamState("done");
          break;
        }

        case "suggestions": {
          const sugg = (event as SSESuggestionsEvent).data.suggestions;
          if (streamDataRef.current) {
            streamDataRef.current.followUps = sugg;
          }
          // Update the last assistant message with follow-ups
          updateLastMessage(sessionId, {
            follow_up_suggestions: sugg,
          });
          break;
        }

        case "awaiting_confirmation": {
          const confirm = (event as SSEAwaitingConfirmationEvent).data;
          const confirmMsg: ChatMessage = {
            message_id: confirm.message_id,
            session_id: sessionId,
            role: "assistant",
            content: confirm.interpretation,
            nl_query: null,
            generated_sql: confirm.sql,
            result_metadata: null,
            follow_up_suggestions: null,
            error: null,
            status: "pending_confirmation",
            created_at: new Date().toISOString(),
          };
          appendMessage(sessionId, confirmMsg);
          setStreamState("done");
          break;
        }

        case "error": {
          const err = (event as SSEErrorEvent).data;
          const errorMsg: ChatMessage = {
            message_id: uuid(),
            session_id: sessionId,
            role: "assistant",
            content: err.error,
            nl_query: null,
            generated_sql: null,
            result_metadata: null,
            follow_up_suggestions: null,
            error: { error: err.error, error_type: err.error_type },
            status: "error",
            created_at: new Date().toISOString(),
          };
          appendMessage(sessionId, errorMsg);
          setStreamState("done");
          break;
        }

        case "done":
          // Stream finished — cleanup handled by onDone callback
          break;
      }
    },
    [
      sessionId,
      appendMessage,
      updateLastMessage,
      setStreamState,
      setPendingInterpretation,
    ],
  );

  // ── Submit query ───────────────────────────────────────────────────────

  const submitQuery = useCallback(
    (query: string) => {
      // Abort any existing stream
      abortRef.current?.abort();

      // Add user message
      const userMsg: ChatMessage = {
        message_id: uuid(),
        session_id: sessionId,
        role: "user",
        content: query,
        nl_query: query,
        generated_sql: null,
        result_metadata: null,
        follow_up_suggestions: null,
        error: null,
        status: null,
        created_at: new Date().toISOString(),
      };
      appendMessage(sessionId, userMsg);

      // Reset streaming state
      setLoading(true);
      setStreamState("thinking");
      setPendingInterpretation(null);
      streamDataRef.current = {
        interpretation: "",
        sql: "",
        rows: [],
        columns: [],
        rowCount: 0,
        truncated: false,
        executionTimeMs: 0,
        attemptCount: 0,
        followUps: [],
        resultContent: "",
      };

      // Open SSE stream
      const controller = createQueryStream(sessionId, query, false, {
        onEvent: handleSSEEvent,
        onError: (err) => {
          const errorMsg: ChatMessage = {
            message_id: uuid(),
            session_id: sessionId,
            role: "assistant",
            content: err.message,
            nl_query: query,
            generated_sql: null,
            result_metadata: null,
            follow_up_suggestions: null,
            error: {
              error: err.message,
              error_type: "execution_error",
            },
            status: "error",
            created_at: new Date().toISOString(),
          };
          appendMessage(sessionId, errorMsg);
          setLoading(false);
          setStreamState(null);
          setPendingInterpretation(null);
          streamDataRef.current = null;
        },
        onDone: () => {
          setLoading(false);
          setStreamState(null);
          setPendingInterpretation(null);
          streamDataRef.current = null;
          // Re-focus the input
          inputRef.current?.focus();
        },
      });

      abortRef.current = controller;
    },
    [
      sessionId,
      appendMessage,
      setLoading,
      setStreamState,
      setPendingInterpretation,
      handleSSEEvent,
    ],
  );

  // ── Confirm query ──────────────────────────────────────────────────────

  const handleConfirm = useCallback(
    (messageId: string) => {
      abortRef.current?.abort();

      // Update the pending message status
      updateLastMessage(sessionId, { status: "confirmed" });

      setLoading(true);
      setStreamState("executing");
      setPendingInterpretation(null);
      streamDataRef.current = {
        interpretation: "",
        sql: "",
        rows: [],
        columns: [],
        rowCount: 0,
        truncated: false,
        executionTimeMs: 0,
        attemptCount: 0,
        followUps: [],
        resultContent: "",
      };

      const controller = createConfirmStream(sessionId, messageId, {
        onEvent: handleSSEEvent,
        onError: (err) => {
          const errorMsg: ChatMessage = {
            message_id: uuid(),
            session_id: sessionId,
            role: "assistant",
            content: err.message,
            nl_query: null,
            generated_sql: null,
            result_metadata: null,
            follow_up_suggestions: null,
            error: {
              error: err.message,
              error_type: "execution_error",
            },
            status: "error",
            created_at: new Date().toISOString(),
          };
          appendMessage(sessionId, errorMsg);
          setLoading(false);
          setStreamState(null);
          setPendingInterpretation(null);
          streamDataRef.current = null;
        },
        onDone: () => {
          setLoading(false);
          setStreamState(null);
          setPendingInterpretation(null);
          streamDataRef.current = null;
          inputRef.current?.focus();
        },
      });

      abortRef.current = controller;
    },
    [
      sessionId,
      updateLastMessage,
      appendMessage,
      setLoading,
      setStreamState,
      setPendingInterpretation,
      handleSSEEvent,
    ],
  );

  // ── Cancel confirmation ────────────────────────────────────────────────

  const handleCancelConfirm = useCallback(() => {
    abortRef.current?.abort();
    // Update the pending message to show it was cancelled
    updateLastMessage(sessionId, {
      status: "error",
      error: { error: "Query cancelled by user.", error_type: "cancelled" },
    });
    setLoading(false);
    setStreamState(null);
    inputRef.current?.focus();
  }, [sessionId, updateLastMessage, setLoading, setStreamState]);

  // ── Retry (Try again) ─────────────────────────────────────────────────

  const handleRetry = useCallback(
    (query: string) => {
      submitQuery(query);
    },
    [submitQuery],
  );

  // ── Follow-up / suggestion select → auto-submit ───────────────────────

  const handleFollowUpSelect = useCallback(
    (query: string) => {
      submitQuery(query);
    },
    [submitQuery],
  );

  const handleSuggestionSelect = useCallback(
    (query: string) => {
      submitQuery(query);
    },
    [submitQuery],
  );

  // ── Render ─────────────────────────────────────────────────────────────

  return (
    <div className="flex h-full flex-col">
      {/* ARIA live region for loading state announcements */}
      <div className="sr-only" aria-live="polite" aria-atomic="true">
        {isLoading && streamState === "thinking" && "Thinking..."}
        {isLoading &&
          streamState === "interpreting" &&
          "Interpreting your query..."}
        {isLoading && streamState === "executing" && "Running query..."}
      </div>

      {/* Chat thread */}
      <ChatThread
        sessionId={sessionId}
        streamState={streamState}
        pendingInterpretation={pendingInterpretation}
        onFollowUpSelect={handleFollowUpSelect}
        onConfirm={handleConfirm}
        onCancelConfirm={handleCancelConfirm}
        onRetry={handleRetry}
        onSuggestionSelect={handleSuggestionSelect}
      />

      {/* Chat input */}
      <ChatInput
        ref={inputRef}
        onSubmit={submitQuery}
        isLoading={isLoading}
      />
    </div>
  );
}

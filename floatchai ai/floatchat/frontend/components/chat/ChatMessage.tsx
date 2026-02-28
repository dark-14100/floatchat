"use client";

/**
 * ChatMessage — Renders a single message with discriminated display.
 *
 * Roles & states:
 * - User:                        right-aligned plain text
 * - Assistant success:           Markdown, collapsible SQL, ResultTable, chart/map slots, follow-ups, metadata
 * - Assistant awaiting_confirm:  interpretation + "Run this query" / "Cancel" buttons
 * - Assistant error:             error message + reformulation suggestion + "Try again"
 * - Assistant loading:           LoadingMessage component
 *
 * Chart/map slots: accept optional React nodes from Features 6/7.
 * No Plotly/Leaflet imports — Hard Rule 4.
 */

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import rehypeSanitize from "rehype-sanitize";
import { User, Bot, ChevronDown, ChevronRight, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";

import type { ChatMessage as ChatMessageType, StreamState } from "@/types/chat";
import ResultTable from "./ResultTable";
import SuggestedFollowUps from "./SuggestedFollowUps";
import LoadingMessage from "./LoadingMessage";

// ── Types ──────────────────────────────────────────────────────────────────

interface ChatMessageProps {
  message: ChatMessageType;
  /** Current SSE stream state — only relevant for the loading message */
  streamState?: StreamState;
  /** Pending interpretation text during SSE stream */
  pendingInterpretation?: string | null;
  /** Chart component slot (Feature 6) */
  chartComponent?: React.ReactNode;
  /** Map component slot (Feature 7) */
  mapComponent?: React.ReactNode;
  /** Callback when a follow-up suggestion is selected */
  onFollowUpSelect?: (query: string) => void;
  /** Callback when "Run this query" is clicked for confirmation */
  onConfirm?: (messageId: string) => void;
  /** Callback when "Cancel" is clicked for confirmation */
  onCancelConfirm?: () => void;
  /** Callback when "Try again" is clicked for errors */
  onRetry?: (query: string) => void;
}

// ── Error type mapping (FR-23) ─────────────────────────────────────────────

const ERROR_MESSAGES: Record<string, { message: string; suggestion: string }> = {
  validation_failure: {
    message: "I couldn't generate a valid query for that.",
    suggestion:
      "Try rephrasing with more specific details about the region, time period, or variable.",
  },
  generation_failure: {
    message: "I had trouble understanding that query after 3 attempts.",
    suggestion: "Try breaking the question into smaller parts.",
  },
  execution_error: {
    message: "The query ran but encountered a database error.",
    suggestion: "Try again, or narrow your filters.",
  },
  timeout: {
    message: "The query took too long to run.",
    suggestion:
      "Try narrowing your filters — add a smaller region or shorter time range.",
  },
  configuration_error: {
    message: "The AI service is not configured.",
    suggestion: "Contact the administrator.",
  },
};

// ── Component ──────────────────────────────────────────────────────────────

export default function ChatMessage({
  message,
  streamState,
  pendingInterpretation,
  chartComponent,
  mapComponent,
  onFollowUpSelect,
  onConfirm,
  onCancelConfirm,
  onRetry,
}: ChatMessageProps) {
  // ── User message ───────────────────────────
  if (message.role === "user") {
    return (
      <div className="flex w-full justify-end">
        <div className="flex max-w-[80%] items-start gap-2">
          <div className="rounded-lg bg-primary px-4 py-2.5 text-sm text-primary-foreground">
            {message.content}
          </div>
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary/20">
            <User className="h-4 w-4 text-primary" />
          </div>
        </div>
      </div>
    );
  }

  // ── Assistant: loading state (placeholder message during SSE) ───────
  if (message.message_id === "__loading__") {
    return (
      <div className="flex w-full justify-start">
        <div className="flex max-w-[80%] items-start gap-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary">
            <Bot className="h-4 w-4 text-muted-foreground" />
          </div>
          <LoadingMessage
            streamState={streamState ?? null}
            interpretation={pendingInterpretation}
          />
        </div>
      </div>
    );
  }

  // ── Assistant: awaiting confirmation ────────
  if (message.status === "pending_confirmation") {
    return (
      <div className="flex w-full justify-start">
        <div className="flex max-w-[80%] items-start gap-2">
          <AssistantAvatar />
          <div className="space-y-3 rounded-lg bg-secondary px-4 py-3 text-sm">
            <p className="text-foreground">{message.content}</p>
            {message.generated_sql && (
              <CollapsibleSQL sql={message.generated_sql} />
            )}
            <div className="flex gap-2">
              <Button
                size="sm"
                onClick={() => onConfirm?.(message.message_id)}
              >
                Run this query
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onCancelConfirm?.()}
              >
                Cancel
              </Button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ── Assistant: error state ─────────────────
  if (message.error) {
    const errorType = message.error.error_type;
    const mapping = ERROR_MESSAGES[errorType] ?? {
      message: message.error.error,
      suggestion: "Try rephrasing your question.",
    };

    return (
      <div className="flex w-full justify-start">
        <div className="flex max-w-[80%] items-start gap-2">
          <AssistantAvatar />
          <div className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm">
            <p className="font-medium text-destructive-foreground">
              {mapping.message}
            </p>
            <p className="text-muted-foreground">{mapping.suggestion}</p>
            {message.nl_query && onRetry && (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onRetry(message.nl_query!)}
                className="gap-1.5"
              >
                <RotateCcw className="h-3 w-3" />
                Try again
              </Button>
            )}
          </div>
        </div>
      </div>
    );
  }

  // ── Assistant: success state ───────────────
  return <SuccessMessage
    message={message}
    chartComponent={chartComponent}
    mapComponent={mapComponent}
    onFollowUpSelect={onFollowUpSelect}
  />;
}

// ── Success sub-component ──────────────────────────────────────────────────

function SuccessMessage({
  message,
  chartComponent,
  mapComponent,
  onFollowUpSelect,
}: {
  message: ChatMessageType;
  chartComponent?: React.ReactNode;
  mapComponent?: React.ReactNode;
  onFollowUpSelect?: (query: string) => void;
}) {
  const hasResults =
    message.result_metadata && message.result_metadata.row_count > 0;
  const emptyResults =
    message.result_metadata && message.result_metadata.row_count === 0;

  return (
    <div className="flex w-full justify-start">
      <div className="flex max-w-[85%] items-start gap-2">
        <AssistantAvatar />
        <div className="min-w-0 space-y-2 rounded-lg bg-secondary px-4 py-3 text-sm">
          {/* Markdown interpretation */}
          <div className="prose prose-sm prose-invert max-w-none break-words">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              rehypePlugins={[rehypeHighlight, rehypeSanitize]}
            >
              {message.content}
            </ReactMarkdown>
          </div>

          {/* Collapsible SQL */}
          {message.generated_sql && (
            <CollapsibleSQL sql={message.generated_sql} />
          )}

          {/* Empty result guidance (FR-24) */}
          {emptyResults && <EmptyResultGuidance query={message.nl_query} />}

          {/* Result table — parse rows from content if result_metadata exists */}
          {hasResults && message.result_metadata && (
            <ResultTable
              columns={message.result_metadata.columns}
              rows={[]} // Rows are populated when results arrive via SSE; stored messages have metadata only
              rowCount={message.result_metadata.row_count}
              truncated={message.result_metadata.truncated}
            />
          )}

          {/* Chart slot (Feature 6) */}
          {chartComponent}

          {/* Map slot (Feature 7) */}
          {mapComponent}

          {/* Metadata line */}
          {message.result_metadata && message.result_metadata.row_count > 0 && (
            <p className="text-xs text-muted-foreground">
              Found {message.result_metadata.row_count.toLocaleString()} profile
              {message.result_metadata.row_count !== 1 ? "s" : ""} in{" "}
              {message.result_metadata.execution_time_ms}ms
            </p>
          )}

          {/* Follow-up suggestions */}
          {message.follow_up_suggestions &&
            message.follow_up_suggestions.length > 0 &&
            onFollowUpSelect && (
              <SuggestedFollowUps
                suggestions={message.follow_up_suggestions}
                onSelect={onFollowUpSelect}
              />
            )}
        </div>
      </div>
    </div>
  );
}

// ── Shared sub-components ──────────────────────────────────────────────────

function AssistantAvatar() {
  return (
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary">
      <Bot className="h-4 w-4 text-muted-foreground" />
    </div>
  );
}

function CollapsibleSQL({ sql }: { sql: string }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="text-xs">
      <button
        onClick={() => setOpen((prev) => !prev)}
        className="inline-flex items-center gap-1 text-muted-foreground hover:text-foreground"
      >
        {open ? (
          <ChevronDown className="h-3 w-3" />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        View SQL
      </button>
      {open && (
        <pre className="mt-1 overflow-x-auto rounded bg-muted/50 p-2 font-mono text-muted-foreground">
          {sql}
        </pre>
      )}
    </div>
  );
}

function EmptyResultGuidance({ query }: { query: string | null }) {
  let guidance = "No data matched your query. Try adjusting the filters.";

  if (query) {
    const lower = query.toLowerCase();
    if (lower.includes("radius") || lower.includes("within") || lower.includes("km")) {
      guidance =
        "No profiles found within that radius. Try expanding the search area.";
    } else if (
      lower.includes("between") ||
      lower.includes("from") ||
      lower.includes("since") ||
      lower.includes("year") ||
      lower.includes("month")
    ) {
      guidance =
        "No profiles found for that time period. Try a wider date range.";
    }
  }

  return (
    <p className="rounded bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
      {guidance}
    </p>
  );
}

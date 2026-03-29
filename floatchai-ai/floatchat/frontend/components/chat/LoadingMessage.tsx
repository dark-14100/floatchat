"use client";

/**
 * LoadingMessage — In-progress assistant message during SSE stream.
 *
 * Renders:
 * - thinking:      animated dots ("Thinking...")
 * - interpreting:  interpretation text
 * - executing:     indeterminate progress bar ("Running query...")
 *
 * CSS animations only — no external animation libraries.
 */

import type { StreamState } from "@/types/chat";

// ── Types ──────────────────────────────────────────────────────────────────

interface LoadingMessageProps {
  streamState: StreamState;
  interpretation?: string | null;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function LoadingMessage({
  streamState,
  interpretation,
}: LoadingMessageProps) {
  if (!streamState || streamState === "done") return null;

  return (
    <div
      className="flex w-full justify-start"
      role="status"
      aria-live="polite"
    >
      <div className="max-w-[80%] rounded-lg bg-secondary px-4 py-3 text-sm text-foreground">
        {streamState === "thinking" && <ThinkingIndicator />}
        {streamState === "interpreting" && (
          <InterpretingIndicator interpretation={interpretation} />
        )}
        {streamState === "executing" && <ExecutingIndicator />}
      </div>
    </div>
  );
}

// ── Sub-components ─────────────────────────────────────────────────────────

function ThinkingIndicator() {
  return (
    <div className="flex items-center gap-2">
      <span className="text-muted-foreground">Thinking</span>
      <span className="flex gap-1" aria-hidden="true">
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
        <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
      </span>
    </div>
  );
}

function InterpretingIndicator({
  interpretation,
}: {
  interpretation?: string | null;
}) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-muted-foreground">
        <span>Interpreting your query</span>
        <span className="flex gap-1" aria-hidden="true">
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:0ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 animate-bounce rounded-full bg-muted-foreground [animation-delay:300ms]" />
        </span>
      </div>
      {interpretation && (
        <p className="text-foreground">{interpretation}</p>
      )}
    </div>
  );
}

function ExecutingIndicator() {
  return (
    <div className="space-y-2">
      <span className="text-muted-foreground">Running query...</span>
      <div
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
        role="progressbar"
        aria-label="Query execution in progress"
      >
        <div className="h-full w-1/3 animate-progress rounded-full bg-primary" />
      </div>
    </div>
  );
}

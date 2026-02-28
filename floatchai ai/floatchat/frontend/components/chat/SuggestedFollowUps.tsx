"use client";

/**
 * SuggestedFollowUps — 2-3 clickable follow-up question chips.
 *
 * Shown below assistant responses. Clicking a chip calls onSelect
 * which should submit the query. Renders nothing if empty.
 */

import { MessageCircleQuestion } from "lucide-react";

// ── Types ──────────────────────────────────────────────────────────────────

interface SuggestedFollowUpsProps {
  suggestions: string[];
  onSelect: (query: string) => void;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function SuggestedFollowUps({
  suggestions,
  onSelect,
}: SuggestedFollowUpsProps) {
  if (!suggestions || suggestions.length === 0) return null;

  return (
    <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Follow-up suggestions">
      {suggestions.map((suggestion, idx) => (
        <button
          key={idx}
          onClick={() => onSelect(suggestion)}
          className="inline-flex items-center gap-1.5 rounded-full border border-border bg-secondary/50 px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:bg-secondary hover:text-foreground"
        >
          <MessageCircleQuestion className="h-3 w-3 shrink-0" />
          <span className="line-clamp-1">{suggestion}</span>
        </button>
      ))}
    </div>
  );
}

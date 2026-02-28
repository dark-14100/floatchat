"use client";

/**
 * SuggestionsPanel — Grid of 4-6 example query cards shown on empty threads.
 *
 * - Calls getLoadTimeSuggestions() on mount
 * - Each card has query + description
 * - onSelect callback submits the query
 * - 4 hardcoded fallbacks on API failure
 */

import { useEffect, useState } from "react";
import { Waves, Thermometer, MapPin, Calendar } from "lucide-react";
import { getLoadTimeSuggestions } from "@/lib/api";
import type { Suggestion } from "@/types/chat";
import { useChatStore } from "@/store/chatStore";

// ── Fallback suggestions ───────────────────────────────────────────────────

const FALLBACK_SUGGESTIONS: Suggestion[] = [
  {
    query: "Show me recent Argo float profiles in the North Atlantic",
    description: "Browse the latest ocean observation data from the North Atlantic basin",
  },
  {
    query: "What is the average sea surface temperature in the Pacific this year?",
    description: "Explore temperature trends across the Pacific Ocean",
  },
  {
    query: "Find deep ocean profiles below 2000m near the Indian Ocean",
    description: "Discover deep-water observations from the Indian Ocean region",
  },
  {
    query: "How many float profiles were collected last month?",
    description: "Get a count of recent ocean observations across all regions",
  },
];

// ── Icons for visual variety ───────────────────────────────────────────────

const CARD_ICONS = [Waves, Thermometer, MapPin, Calendar, Waves, Thermometer];

// ── Types ──────────────────────────────────────────────────────────────────

interface SuggestionsPanelProps {
  onSelect: (query: string) => void;
}

// ── Component ──────────────────────────────────────────────────────────────

export default function SuggestionsPanel({ onSelect }: SuggestionsPanelProps) {
  const storeSuggestions = useChatStore((s) => s.loadTimeSuggestions);
  const setLoadTimeSuggestions = useChatStore((s) => s.setLoadTimeSuggestions);
  const [suggestions, setSuggestions] = useState<Suggestion[]>(
    storeSuggestions.length > 0 ? storeSuggestions : [],
  );
  const [loaded, setLoaded] = useState(storeSuggestions.length > 0);

  useEffect(() => {
    if (loaded) return;

    let cancelled = false;

    async function load() {
      try {
        const data = await getLoadTimeSuggestions();
        if (!cancelled && data.length > 0) {
          setSuggestions(data);
          setLoadTimeSuggestions(data);
        } else if (!cancelled) {
          setSuggestions(FALLBACK_SUGGESTIONS);
          setLoadTimeSuggestions(FALLBACK_SUGGESTIONS);
        }
      } catch {
        if (!cancelled) {
          setSuggestions(FALLBACK_SUGGESTIONS);
          setLoadTimeSuggestions(FALLBACK_SUGGESTIONS);
        }
      } finally {
        if (!cancelled) setLoaded(true);
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [loaded, setLoadTimeSuggestions]);

  const displaySuggestions =
    suggestions.length > 0 ? suggestions : FALLBACK_SUGGESTIONS;

  return (
    <div className="flex h-full flex-col items-center justify-center px-4 py-12">
      <div className="mb-8 text-center">
        <h2 className="text-xl font-semibold text-foreground">
          What would you like to explore?
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Ask a question about ocean data, or try one of these examples
        </p>
      </div>

      <div className="grid w-full max-w-2xl grid-cols-1 gap-3 sm:grid-cols-2">
        {displaySuggestions.map((suggestion, idx) => {
          const Icon = CARD_ICONS[idx % CARD_ICONS.length];
          return (
            <button
              key={idx}
              onClick={() => onSelect(suggestion.query)}
              className="group flex items-start gap-3 rounded-lg border border-border bg-secondary/30 p-4 text-left transition-colors hover:border-primary/40 hover:bg-secondary/60"
            >
              <Icon className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground group-hover:text-primary" />
              <div className="min-w-0 space-y-1">
                <p className="text-sm font-medium text-foreground line-clamp-2">
                  {suggestion.query}
                </p>
                <p className="text-xs text-muted-foreground line-clamp-2">
                  {suggestion.description}
                </p>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

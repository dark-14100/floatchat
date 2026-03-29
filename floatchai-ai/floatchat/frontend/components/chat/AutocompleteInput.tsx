"use client";

import Fuse, { type IFuseOptions } from "fuse.js";
import { SendHorizonal, Loader2 } from "lucide-react";
import {
  forwardRef,
  useCallback,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  type ChangeEvent,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";
import oceanTermsData from "@/lib/oceanTerms.json";
import templatesData from "@/lib/queryTemplates.json";

export interface AutocompleteInputHandle {
  focus: () => void;
}

export type SubmitSource = "free_text" | "history" | "template" | "term";

export interface SubmitOptions {
  bypassClarification?: boolean;
  source?: SubmitSource;
}

interface AutocompleteInputProps {
  onSubmit: (value: string, options?: SubmitOptions) => void;
  isLoading: boolean;
  placeholder?: string;
  userId?: string;
  disabled?: boolean;
}

interface QueryTemplate {
  id: string;
  category: string;
  label: string;
  query: string;
  description: string;
  variables: string[];
  requiresAuth: boolean;
}

interface OceanTerm {
  term: string;
  aliases: string[];
  category: string;
}

interface QueryHistoryEntry {
  nl_query: string;
  created_at: string;
}

interface SuggestionItem {
  id: string;
  source: "history" | "template" | "term";
  primaryText: string;
  secondaryText?: string;
  insertText: string;
  score: number;
  highlightRanges: Array<[number, number]>;
  dateText?: string;
}

const MAX_HEIGHT = 144;
const LINE_HEIGHT = 24;
const CHAR_WARN_THRESHOLD = 450;
const MAX_SUGGESTIONS = 8;
const MIN_QUERY_LENGTH = 2;

const TEMPLATE_FUSE_OPTIONS: IFuseOptions<QueryTemplate> = {
  includeScore: true,
  includeMatches: true,
  threshold: 0.4,
  distance: 100,
  minMatchCharLength: 2,
  keys: [
    { name: "label", weight: 0.5 },
    { name: "query", weight: 0.3 },
    { name: "description", weight: 0.2 },
  ],
};

const HISTORY_FUSE_OPTIONS: IFuseOptions<QueryHistoryEntry> = {
  includeScore: true,
  includeMatches: true,
  threshold: 0.4,
  distance: 100,
  minMatchCharLength: 2,
  keys: [{ name: "nl_query", weight: 1 }],
};

const TERM_FUSE_OPTIONS: IFuseOptions<OceanTerm> = {
  includeScore: true,
  includeMatches: true,
  threshold: 0.4,
  distance: 100,
  minMatchCharLength: 2,
  keys: [
    { name: "term", weight: 0.7 },
    { name: "aliases", weight: 0.3 },
  ],
};

function normalizeRanges(indices?: ReadonlyArray<readonly [number, number]>): Array<[number, number]> {
  if (!indices || indices.length === 0) {
    return [];
  }

  return indices
    .filter((range) => range[0] >= 0 && range[1] >= range[0])
    .map((range) => [range[0], range[1]]);
}

function renderHighlightedText(text: string, ranges: Array<[number, number]>): ReactNode {
  if (ranges.length === 0) {
    return text;
  }

  const segments: ReactNode[] = [];
  let cursor = 0;

  for (let i = 0; i < ranges.length; i += 1) {
    const [start, end] = ranges[i];
    if (start > cursor) {
      segments.push(text.slice(cursor, start));
    }
    segments.push(
      <mark
        key={`${start}-${end}`}
        className="rounded bg-primary/15 px-0.5 text-foreground"
      >
        {text.slice(start, end + 1)}
      </mark>,
    );
    cursor = end + 1;
  }

  if (cursor < text.length) {
    segments.push(text.slice(cursor));
  }

  return segments;
}

function formatDateLabel(value: string): string | undefined {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return undefined;
  }

  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

const AutocompleteInput = forwardRef<AutocompleteInputHandle, AutocompleteInputProps>(
  (
    {
      onSubmit,
      isLoading,
      placeholder = "Ask about ocean data...",
      userId,
      disabled = false,
    },
    ref,
  ) => {
    const wrapperRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const historyFetchedRef = useRef(false);

    const [value, setValue] = useState("");
    const [isFocused, setIsFocused] = useState(false);
    const [isOpen, setIsOpen] = useState(false);
    const [activeIndex, setActiveIndex] = useState(-1);
    const [historyEntries, setHistoryEntries] = useState<QueryHistoryEntry[]>([]);
    const [selectedMeta, setSelectedMeta] = useState<{
      text: string;
      source: "history" | "template" | "term";
    } | null>(null);

    const templates = useMemo(
      () => ((templatesData as { templates?: QueryTemplate[] }).templates ?? []),
      [],
    );

    const oceanTerms = useMemo(
      () => ((oceanTermsData as { terms?: OceanTerm[] }).terms ?? []),
      [],
    );

    const templateFuse = useMemo(
      () => new Fuse(templates, TEMPLATE_FUSE_OPTIONS),
      [templates],
    );

    const termFuse = useMemo(
      () => new Fuse(oceanTerms, TERM_FUSE_OPTIONS),
      [oceanTerms],
    );

    const historyFuse = useMemo(
      () =>
        historyEntries.length > 0
          ? new Fuse(historyEntries, HISTORY_FUSE_OPTIONS)
          : null,
      [historyEntries],
    );

    useImperativeHandle(ref, () => ({
      focus: () => textareaRef.current?.focus(),
    }));

    useEffect(() => {
      if (!userId || historyFetchedRef.current) {
        return;
      }

      historyFetchedRef.current = true;
      let cancelled = false;

      async function loadHistory(): Promise<void> {
        try {
          const data = await apiFetch<QueryHistoryEntry[]>("/chat/query-history?limit=200", {
            method: "GET",
          });

          if (!cancelled) {
            setHistoryEntries(data);
          }
        } catch {
          if (!cancelled) {
            setHistoryEntries([]);
          }
        }
      }

      void loadHistory();

      return () => {
        cancelled = true;
      };
    }, [userId]);

    useEffect(() => {
      function handleOutsideClick(event: MouseEvent): void {
        const target = event.target as Node;
        if (!wrapperRef.current?.contains(target)) {
          setIsOpen(false);
          setActiveIndex(-1);
        }
      }

      document.addEventListener("mousedown", handleOutsideClick);
      return () => {
        document.removeEventListener("mousedown", handleOutsideClick);
      };
    }, []);

    const suggestions = useMemo(() => {
      const query = value.trim();
      if (query.length < MIN_QUERY_LENGTH) {
        return [] as SuggestionItem[];
      }

      const historySuggestions: SuggestionItem[] = historyFuse
        ? historyFuse
            .search(query, { limit: MAX_SUGGESTIONS })
            .map((result, index) => {
              const match = result.matches?.find((m) => m.key === "nl_query");
              return {
                id: `history-${index}-${result.item.created_at}`,
                source: "history" as const,
                primaryText: result.item.nl_query,
                secondaryText: "Past query",
                insertText: result.item.nl_query,
                score: result.score ?? 1,
                highlightRanges: normalizeRanges(match?.indices),
                dateText: formatDateLabel(result.item.created_at),
              };
            })
            .sort((a, b) => a.score - b.score)
        : [];

      const templateSuggestions: SuggestionItem[] = templateFuse
        .search(query, { limit: MAX_SUGGESTIONS })
        .map((result, index) => {
          const match = result.matches?.find((m) => m.key === "query");
          return {
            id: `template-${index}-${result.item.id}`,
            source: "template" as const,
            primaryText: result.item.query,
            secondaryText: result.item.label,
            insertText: result.item.query,
            score: result.score ?? 1,
            highlightRanges: normalizeRanges(match?.indices),
          };
        })
        .sort((a, b) => a.score - b.score);

      const termSuggestions: SuggestionItem[] = termFuse
        .search(query, { limit: MAX_SUGGESTIONS })
        .map((result, index) => {
          const match = result.matches?.find((m) => m.key === "term");
          return {
            id: `term-${index}-${result.item.term}`,
            source: "term" as const,
            primaryText: result.item.term,
            secondaryText: `Term (${result.item.category})`,
            insertText: result.item.term,
            score: result.score ?? 1,
            highlightRanges: normalizeRanges(match?.indices),
          };
        })
        .sort((a, b) => a.score - b.score);

      const merged: SuggestionItem[] = [];
      const seen = new Set<string>();

      for (const group of [historySuggestions, templateSuggestions, termSuggestions]) {
        for (const item of group) {
          const key = item.insertText.trim().toLowerCase();
          if (!key || seen.has(key)) {
            continue;
          }
          seen.add(key);
          merged.push(item);
          if (merged.length >= MAX_SUGGESTIONS) {
            return merged;
          }
        }
      }

      return merged;
    }, [historyFuse, templateFuse, termFuse, value]);

    useEffect(() => {
      if (!isFocused || suggestions.length === 0 || value.trim().length < MIN_QUERY_LENGTH) {
        setIsOpen(false);
        setActiveIndex(-1);
        return;
      }

      setIsOpen(true);
      setActiveIndex((prev) => {
        if (prev < 0) return 0;
        if (prev >= suggestions.length) return suggestions.length - 1;
        return prev;
      });
    }, [isFocused, suggestions, value]);

    const adjustHeight = useCallback(() => {
      const el = textareaRef.current;
      if (!el) return;
      el.style.height = `${LINE_HEIGHT}px`;
      const newHeight = Math.min(el.scrollHeight, MAX_HEIGHT);
      el.style.height = `${newHeight}px`;
    }, []);

    const handleChange = useCallback(
      (e: ChangeEvent<HTMLTextAreaElement>) => {
        setValue(e.target.value);
        setSelectedMeta(null);
        adjustHeight();
      },
      [adjustHeight],
    );

    const handleSuggestionSelect = useCallback(
      (item: SuggestionItem) => {
        setValue(item.insertText);
        setSelectedMeta({
          text: item.insertText,
          source: item.source,
        });
        setIsOpen(false);
        setActiveIndex(-1);
        requestAnimationFrame(() => {
          textareaRef.current?.focus();
          adjustHeight();
        });
      },
      [adjustHeight],
    );

    const handleSubmit = useCallback(() => {
      const trimmed = value.trim();
      if (!trimmed || isLoading || disabled) {
        return;
      }

      const fromSelection =
        !!selectedMeta && selectedMeta.text.trim().toLowerCase() === trimmed.toLowerCase();

      onSubmit(trimmed, {
        bypassClarification: fromSelection,
        source: fromSelection ? selectedMeta.source : "free_text",
      });

      setValue("");
      setSelectedMeta(null);
      setIsOpen(false);
      setActiveIndex(-1);

      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (el) {
          el.style.height = `${LINE_HEIGHT}px`;
        }
      });
    }, [value, isLoading, disabled, selectedMeta, onSubmit]);

    const handleKeyDown = useCallback(
      (e: KeyboardEvent<HTMLTextAreaElement>) => {
        if (e.key === "ArrowDown" && suggestions.length > 0) {
          e.preventDefault();
          setIsOpen(true);
          setActiveIndex((prev) => {
            if (prev < 0) return 0;
            return Math.min(prev + 1, suggestions.length - 1);
          });
          return;
        }

        if (e.key === "ArrowUp" && suggestions.length > 0) {
          e.preventDefault();
          setIsOpen(true);
          setActiveIndex((prev) => {
            if (prev <= 0) return 0;
            return prev - 1;
          });
          return;
        }

        if (e.key === "Escape") {
          if (isOpen) {
            e.preventDefault();
            setIsOpen(false);
            setActiveIndex(-1);
          }
          return;
        }

        if (e.key === "Enter" && !e.shiftKey) {
          if (isOpen && activeIndex >= 0 && activeIndex < suggestions.length) {
            e.preventDefault();
            handleSuggestionSelect(suggestions[activeIndex]);
            return;
          }

          e.preventDefault();
          handleSubmit();
        }
      },
      [activeIndex, handleSubmit, handleSuggestionSelect, isOpen, suggestions],
    );

    const isInputDisabled = isLoading || disabled;

    return (
      <div className="border-t border-border bg-background px-4 py-3">
        <div className="mx-auto flex max-w-3xl items-end gap-2">
          <div ref={wrapperRef} className="relative flex-1">
            {isOpen && suggestions.length > 0 ? (
              <div
                className="absolute bottom-full z-20 mb-2 max-h-64 w-full overflow-y-auto rounded-lg border border-border bg-background shadow-lg"
                role="listbox"
                aria-label="Autocomplete suggestions"
              >
                {suggestions.map((item, index) => {
                  const active = index === activeIndex;
                  return (
                    <button
                      key={item.id}
                      type="button"
                      role="option"
                      aria-selected={active}
                      onMouseDown={(event) => {
                        event.preventDefault();
                      }}
                      onClick={() => handleSuggestionSelect(item)}
                      className={
                        active
                          ? "w-full border-b border-border bg-secondary/70 px-3 py-2 text-left last:border-b-0"
                          : "w-full border-b border-border bg-background px-3 py-2 text-left hover:bg-secondary/40 last:border-b-0"
                      }
                    >
                      <div className="mb-1 flex items-center gap-2">
                        <span className="text-xs font-semibold text-foreground">
                          {renderHighlightedText(item.primaryText, item.highlightRanges)}
                        </span>
                        <span className="rounded border border-border bg-secondary px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                          {item.source === "history"
                            ? "Past query"
                            : item.source === "template"
                              ? "Template"
                              : "Term"}
                        </span>
                        {item.dateText ? (
                          <span className="text-[10px] text-muted-foreground">{item.dateText}</span>
                        ) : null}
                      </div>
                      {item.secondaryText ? (
                        <p className="line-clamp-1 text-[11px] text-muted-foreground">{item.secondaryText}</p>
                      ) : null}
                    </button>
                  );
                })}
              </div>
            ) : null}

            <textarea
              ref={textareaRef}
              value={value}
              onFocus={() => setIsFocused(true)}
              onBlur={() => setIsFocused(false)}
              onChange={handleChange}
              onKeyDown={handleKeyDown}
              placeholder={placeholder}
              disabled={isInputDisabled}
              rows={1}
              aria-label="Chat message input"
              className="w-full resize-none rounded-lg border border-input bg-secondary px-4 py-3 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
              style={{ height: `${LINE_HEIGHT}px`, maxHeight: `${MAX_HEIGHT}px` }}
            />

            {value.length > CHAR_WARN_THRESHOLD ? (
              <span className="absolute bottom-1 right-3 text-xs text-muted-foreground">
                {value.length}
              </span>
            ) : null}
          </div>

          <Button
            size="icon"
            onClick={handleSubmit}
            disabled={isInputDisabled || !value.trim()}
            aria-label="Send message"
            className="h-10 w-10 shrink-0"
          >
            {isLoading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <SendHorizonal className="h-4 w-4" />
            )}
          </Button>
        </div>
      </div>
    );
  },
);

AutocompleteInput.displayName = "AutocompleteInput";

export default AutocompleteInput;

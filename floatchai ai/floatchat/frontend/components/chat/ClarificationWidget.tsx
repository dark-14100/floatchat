"use client";

import { useEffect, useMemo, useState } from "react";
import { Loader2, X } from "lucide-react";
import { Button } from "@/components/ui/button";

export interface ClarificationQuestion {
  dimension: string;
  question_text: string;
  options: string[];
}

interface ClarificationWidgetProps {
  visible: boolean;
  isLoading: boolean;
  originalQuery: string;
  missingDimensions: string[];
  clarificationQuestions: ClarificationQuestion[];
  onAssembledQuery: (query: string) => void;
  onSkip: () => void;
  onDismiss: () => void;
}

function buildAssembledQuery(
  originalQuery: string,
  missingDimensions: string[],
  selections: Record<string, string>,
): string {
  const details = missingDimensions
    .map((dimension) => ({
      dimension,
      value: selections[dimension]?.trim() ?? "",
    }))
    .filter((item) => item.value.length > 0)
    .map((item) => `${item.dimension}: ${item.value}`);

  if (details.length === 0) {
    return originalQuery;
  }

  return `${originalQuery.trim()}, specifically ${details.join(", ")}`;
}

export default function ClarificationWidget({
  visible,
  isLoading,
  originalQuery,
  missingDimensions,
  clarificationQuestions,
  onAssembledQuery,
  onSkip,
  onDismiss,
}: ClarificationWidgetProps) {
  const [selections, setSelections] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!visible) {
      setSelections({});
      return;
    }

    setSelections({});
  }, [visible, originalQuery]);

  const questionMap = useMemo(() => {
    const map = new Map<string, ClarificationQuestion>();
    for (const question of clarificationQuestions) {
      if (!map.has(question.dimension)) {
        map.set(question.dimension, question);
      }
    }
    return map;
  }, [clarificationQuestions]);

  const allDimensionsSelected = useMemo(() => {
    if (missingDimensions.length === 0) {
      return false;
    }

    return missingDimensions.every((dimension) => {
      const value = selections[dimension];
      return typeof value === "string" && value.trim().length > 0;
    });
  }, [missingDimensions, selections]);

  if (!visible) {
    return null;
  }

  return (
    <section className="border-t border-border bg-secondary/20 px-4 py-3" aria-live="polite">
      <div className="mx-auto max-w-3xl rounded-lg border border-border bg-background p-4">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Refine your query</h3>
            <p className="mt-1 text-xs text-muted-foreground">
              Your query needs a bit more detail. Answer a few questions to get the best results.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label="Dismiss clarification"
            onClick={onDismiss}
            className="h-7 w-7"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {isLoading ? (
          <div className="flex items-center gap-2 rounded-md border border-border bg-secondary/30 px-3 py-2 text-xs text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Detecting missing details...
          </div>
        ) : (
          <div className="space-y-3">
            {missingDimensions.map((dimension) => {
              const question = questionMap.get(dimension);
              if (!question) {
                return null;
              }

              const selected = selections[dimension] ?? "";

              return (
                <div key={dimension}>
                  <p className="mb-2 text-xs font-medium text-foreground">{question.question_text}</p>
                  <div className="flex flex-wrap gap-2" role="group" aria-label={question.question_text}>
                    {question.options.map((option) => {
                      const active = selected === option;
                      return (
                        <button
                          key={`${dimension}-${option}`}
                          type="button"
                          aria-pressed={active}
                          onClick={() => {
                            setSelections((prev) => ({
                              ...prev,
                              [dimension]: option,
                            }));
                          }}
                          className={
                            active
                              ? "rounded-full border border-primary bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
                              : "rounded-full border border-border bg-secondary/40 px-3 py-1.5 text-xs text-foreground hover:border-primary/40 hover:bg-secondary"
                          }
                        >
                          {option}
                        </button>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center justify-between gap-2">
          <button
            type="button"
            onClick={onSkip}
            className="text-xs text-muted-foreground underline-offset-4 hover:text-foreground hover:underline"
          >
            Skip and run anyway
          </button>

          <Button
            type="button"
            onClick={() => {
              const assembled = buildAssembledQuery(
                originalQuery,
                missingDimensions,
                selections,
              );
              onAssembledQuery(assembled);
            }}
            disabled={isLoading || !allDimensionsSelected}
            size="sm"
          >
            Run query
          </Button>
        </div>
      </div>
    </section>
  );
}

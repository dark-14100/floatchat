"use client";

import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "@/lib/api";
import templatesData from "@/lib/queryTemplates.json";

type TemplateCategory =
  | "Temperature"
  | "Salinity"
  | "BGC Floats"
  | "Regional Comparison"
  | "Time Series"
  | "Float Tracking"
  | "Depth Analysis"
  | "Anomalies";

interface QueryTemplate {
  id: string;
  category: TemplateCategory;
  label: string;
  query: string;
  description: string;
  variables: string[];
  requiresAuth: boolean;
}

interface QueryHistoryEntry {
  nl_query: string;
  created_at: string;
}

interface DatasetSummary {
  variable_list?: unknown;
  date_range_end?: string | null;
}

interface DatasetSummariesResponse {
  results: DatasetSummary[];
  count: number;
}

interface SuggestedQueryGalleryProps {
  onQuerySelect: (query: string) => void;
  userId?: string;
  visible: boolean;
}

const CATEGORIES: TemplateCategory[] = [
  "Temperature",
  "Salinity",
  "BGC Floats",
  "Regional Comparison",
  "Time Series",
  "Float Tracking",
  "Depth Analysis",
  "Anomalies",
];

const VARIABLE_PATTERNS: Array<{ key: string; patterns: string[] }> = [
  { key: "temperature", patterns: ["temperature", "temp"] },
  { key: "salinity", patterns: ["salinity", "psal"] },
  { key: "dissolved oxygen", patterns: ["dissolved oxygen", "oxygen", "doxy"] },
  { key: "chlorophyll", patterns: ["chlorophyll", "chla"] },
  { key: "nitrate", patterns: ["nitrate"] },
  { key: "ph", patterns: ["ph", "pH"] },
];

const REGION_PATTERNS: string[] = [
  "indian ocean",
  "north atlantic",
  "south atlantic",
  "north pacific",
  "south pacific",
  "southern ocean",
  "arctic ocean",
  "arabian sea",
  "bay of bengal",
  "mediterranean sea",
  "gulf of mexico",
  "pacific ocean",
  "atlantic ocean",
];

function normalizeVariableName(value: string): string {
  const v = value.trim().toLowerCase();
  if (v === "temp") return "temperature";
  if (v === "psal") return "salinity";
  if (v === "doxy") return "dissolved oxygen";
  if (v === "chla") return "chlorophyll";
  if (v === "ph") return "ph";
  return v;
}

function extractVariableNames(variableList: unknown): string[] {
  if (!variableList) return [];

  if (Array.isArray(variableList)) {
    return variableList
      .filter((v): v is string => typeof v === "string")
      .map(normalizeVariableName);
  }

  if (typeof variableList === "object") {
    const obj = variableList as Record<string, unknown>;
    return Object.keys(obj).map(normalizeVariableName);
  }

  return [];
}

function buildForYouTemplates(history: QueryHistoryEntry[]): QueryTemplate[] {
  const variableHits = new Map<string, number>();
  const regionHits = new Map<string, number>();

  for (const entry of history) {
    const query = entry.nl_query.toLowerCase();

    for (const variable of VARIABLE_PATTERNS) {
      if (variable.patterns.some((token) => query.includes(token.toLowerCase()))) {
        variableHits.set(variable.key, (variableHits.get(variable.key) ?? 0) + 1);
      }
    }

    for (const region of REGION_PATTERNS) {
      if (query.includes(region)) {
        regionHits.set(region, (regionHits.get(region) ?? 0) + 1);
      }
    }
  }

  const topVariable = Array.from(variableHits.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];
  const topRegion = Array.from(regionHits.entries()).sort((a, b) => b[1] - a[1])[0]?.[0];

  const forYou: QueryTemplate[] = [];

  if (topVariable && topRegion) {
    forYou.push({
      id: "for_you_top_var_region",
      category: "Temperature",
      label: `Your Frequent Combo: ${topVariable} in ${topRegion}`,
      query: `Show ${topVariable} profiles in the ${topRegion} over the last 6 months.`,
      description: "Generated from your most frequent variable and region usage.",
      variables: [topVariable],
      requiresAuth: false,
    });
  }

  if (topVariable) {
    forYou.push({
      id: "for_you_top_variable_trend",
      category: "Temperature",
      label: `Trend Focus: ${topVariable}`,
      query: `Show monthly trends for ${topVariable} across all regions over the last 2 years.`,
      description: "Generated from your most frequently queried variable.",
      variables: [topVariable],
      requiresAuth: false,
    });
  }

  if (topRegion) {
    forYou.push({
      id: "for_you_top_region_summary",
      category: "Regional Comparison",
      label: `Region Focus: ${topRegion}`,
      query: `Summarize recent temperature and salinity conditions in the ${topRegion}.`,
      description: "Generated from your most frequently queried region.",
      variables: ["temperature", "salinity"],
      requiresAuth: false,
    });
  }

  const seenQueries = new Set<string>();
  for (const entry of history) {
    const query = entry.nl_query.trim();
    if (!query || seenQueries.has(query)) continue;
    seenQueries.add(query);

    forYou.push({
      id: `for_you_history_${forYou.length + 1}`,
      category: "Time Series",
      label: "From Your History",
      query,
      description: "A successful query from your recent history.",
      variables: [],
      requiresAuth: false,
    });

    if (forYou.length >= 6) break;
  }

  return forYou.slice(0, 6);
}

export default function SuggestedQueryGallery({
  onQuerySelect,
  userId,
  visible,
}: SuggestedQueryGalleryProps) {
  const templates = useMemo(
    () => (templatesData.templates as QueryTemplate[]) ?? [],
    [],
  );

  const [selectedCategory, setSelectedCategory] = useState<string>("Temperature");
  const [forYouTemplates, setForYouTemplates] = useState<QueryTemplate[]>([]);
  const [recentVariables, setRecentVariables] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!userId) {
      setForYouTemplates([]);
      return;
    }

    let cancelled = false;

    async function loadForYou(): Promise<void> {
      try {
        const history = await apiFetch<QueryHistoryEntry[]>("/chat/query-history", {
          method: "GET",
        });

        if (cancelled) return;
        if (history.length < 5) {
          setForYouTemplates([]);
          return;
        }

        setForYouTemplates(buildForYouTemplates(history));
      } catch {
        if (!cancelled) {
          setForYouTemplates([]);
        }
      }
    }

    void loadForYou();
    return () => {
      cancelled = true;
    };
  }, [userId]);

  useEffect(() => {
    let cancelled = false;

    async function loadRecentlyAddedVariables(): Promise<void> {
      try {
        const response = await apiFetch<DatasetSummariesResponse>("/search/datasets/summaries", {
          method: "GET",
        });

        if (cancelled) return;

        const sevenDaysAgo = new Date();
        sevenDaysAgo.setDate(sevenDaysAgo.getDate() - 7);

        const vars = new Set<string>();
        for (const dataset of response.results ?? []) {
          const date = dataset.date_range_end ? new Date(dataset.date_range_end) : null;
          if (!date || Number.isNaN(date.getTime()) || date < sevenDaysAgo) {
            continue;
          }

          for (const variable of extractVariableNames(dataset.variable_list)) {
            vars.add(variable);
          }
        }

        setRecentVariables(vars);
      } catch {
        if (!cancelled) {
          // Silent omission on failure per requirement.
          setRecentVariables(new Set());
        }
      }
    }

    void loadRecentlyAddedVariables();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const hasForYou = forYouTemplates.length > 0;
    if (hasForYou && selectedCategory !== "For You") return;
    if (!hasForYou && selectedCategory === "For You") {
      setSelectedCategory("Temperature");
    }
  }, [forYouTemplates.length, selectedCategory]);

  if (!visible) {
    return null;
  }

  const categoryTabs = [
    ...(forYouTemplates.length > 0 ? ["For You"] : []),
    ...CATEGORIES,
  ];

  const cards =
    selectedCategory === "For You"
      ? forYouTemplates
      : templates.filter((template) => template.category === selectedCategory);

  return (
    <div className="flex h-full flex-col items-center justify-center px-4 py-8">
      <div className="mb-6 text-center">
        <h2 className="text-xl font-semibold text-foreground">Start With a Guided Query</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Choose a template to run immediately, or switch categories to explore more ideas.
        </p>
      </div>

      <div className="mb-4 flex w-full max-w-5xl flex-wrap gap-2">
        {categoryTabs.map((category) => {
          const active = selectedCategory === category;
          return (
            <button
              key={category}
              type="button"
              onClick={() => setSelectedCategory(category)}
              className={
                active
                  ? "rounded-full border border-primary bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground"
                  : "rounded-full border border-border bg-background px-3 py-1.5 text-xs font-medium text-foreground hover:bg-secondary"
              }
            >
              {category}
            </button>
          );
        })}
      </div>

      <div className="grid w-full max-w-5xl grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {cards.map((card) => {
          const hasRecentVariable = card.variables.some((v) =>
            recentVariables.has(normalizeVariableName(v)),
          );

          return (
            <button
              key={card.id}
              type="button"
              onClick={() => onQuerySelect(card.query)}
              className="group flex h-full flex-col rounded-lg border border-border bg-secondary/20 p-4 text-left transition-colors hover:border-primary/40 hover:bg-secondary/50"
            >
              <div className="mb-2 flex items-start justify-between gap-2">
                <p className="text-sm font-semibold text-foreground">{card.label}</p>
                {hasRecentVariable ? (
                  <span className="shrink-0 rounded-full border border-emerald-300 bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-800">
                    Recently Added
                  </span>
                ) : null}
              </div>

              <p className="mb-3 text-xs text-muted-foreground">{card.description}</p>

              <div className="mt-auto flex flex-wrap gap-1.5">
                {card.variables.length > 0 ? (
                  card.variables.map((variable) => (
                    <span
                      key={`${card.id}-${variable}`}
                      className="rounded-md border border-border bg-background px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground"
                    >
                      {variable}
                    </span>
                  ))
                ) : (
                  <span className="rounded-md border border-border bg-background px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                    personalized
                  </span>
                )}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

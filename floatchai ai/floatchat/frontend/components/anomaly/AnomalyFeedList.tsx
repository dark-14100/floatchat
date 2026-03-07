"use client";

import { useEffect, useMemo, useState } from "react";

import { getAnomalies } from "@/lib/anomalyQueries";
import type { AnomalyListItem, AnomalySeverity, AnomalyType } from "@/types/anomaly";

interface AnomalyFeedListProps {
  selectedAnomalyId: string | null;
  onSelectAnomaly: (anomalyId: string) => void;
  refreshToken?: number;
}

const ANOMALY_TYPES: Array<{ value: "" | AnomalyType; label: string }> = [
  { value: "", label: "All types" },
  { value: "spatial_baseline", label: "Spatial baseline" },
  { value: "float_self_comparison", label: "Float self-comparison" },
  { value: "cluster_pattern", label: "Cluster pattern" },
  { value: "seasonal_baseline", label: "Seasonal baseline" },
];

function severityDotClass(severity: AnomalySeverity): string {
  if (severity === "high") return "bg-[var(--color-coral)]";
  if (severity === "medium") return "bg-[var(--color-sand)]";
  return "bg-[var(--color-seafoam)]";
}

export default function AnomalyFeedList({ selectedAnomalyId, onSelectAnomaly, refreshToken = 0 }: AnomalyFeedListProps) {
  const [items, setItems] = useState<AnomalyListItem[]>([]);
  const [loading, setLoading] = useState(true);

  const [severity, setSeverity] = useState<"" | AnomalySeverity>("");
  const [anomalyType, setAnomalyType] = useState<"" | AnomalyType>("");
  const [variable, setVariable] = useState("");
  const [reviewedFilter, setReviewedFilter] = useState<"all" | "true" | "false">("all");

  useEffect(() => {
    let mounted = true;

    setLoading(true);
    const isReviewed = reviewedFilter === "all" ? undefined : reviewedFilter === "true";

    getAnomalies({
      days: 7,
      limit: 200,
      offset: 0,
      severity: severity || undefined,
      anomaly_type: anomalyType || undefined,
      variable: variable.trim() || undefined,
      is_reviewed: isReviewed,
    })
      .then((res) => {
        if (!mounted) return;
        setItems(res.items);
      })
      .catch(() => {
        if (!mounted) return;
        setItems([]);
      })
      .finally(() => {
        if (!mounted) return;
        setLoading(false);
      });

    return () => {
      mounted = false;
    };
  }, [anomalyType, reviewedFilter, severity, variable, refreshToken]);

  const headerText = useMemo(() => {
    if (loading) return "Loading anomalies…";
    if (items.length === 0) return "No anomalies found for the current filters.";
    return `${items.length} anomalies`;
  }, [items.length, loading]);

  return (
    <div className="flex h-full flex-col rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)]">
      <div className="border-b border-[var(--color-border-subtle)] p-3">
        <div className="mb-2 text-sm font-semibold text-[var(--color-text-primary)]">Anomaly Feed</div>

        <div className="grid grid-cols-2 gap-2 text-xs md:grid-cols-4">
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value as "" | AnomalySeverity)}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-[var(--color-text-primary)]"
          >
            <option value="">All severities</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>

          <select
            value={anomalyType}
            onChange={(e) => setAnomalyType(e.target.value as "" | AnomalyType)}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-[var(--color-text-primary)]"
          >
            {ANOMALY_TYPES.map((entry) => (
              <option key={entry.label} value={entry.value}>
                {entry.label}
              </option>
            ))}
          </select>

          <select
            value={reviewedFilter}
            onChange={(e) => setReviewedFilter(e.target.value as "all" | "true" | "false")}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-[var(--color-text-primary)]"
          >
            <option value="all">All statuses</option>
            <option value="false">Unreviewed</option>
            <option value="true">Reviewed</option>
          </select>

          <input
            value={variable}
            onChange={(e) => setVariable(e.target.value)}
            placeholder="Variable"
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-[var(--color-text-primary)]"
          />
        </div>

        <div className="mt-2 text-xs text-[var(--color-text-secondary)]">{headerText}</div>
      </div>

      <div className="flex-1 overflow-y-auto p-2">
        {items.map((item) => {
          const selected = item.anomaly_id === selectedAnomalyId;
          return (
            <button
              key={item.anomaly_id}
              onClick={() => onSelectAnomaly(item.anomaly_id)}
              className={[
                "mb-2 w-full rounded-md border px-3 py-2 text-left transition-colors",
                selected
                  ? "border-[var(--color-ocean-primary)] bg-[var(--color-ocean-lighter)]"
                  : "border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] hover:border-[var(--color-border-default)]",
              ].join(" ")}
            >
              <div className="flex items-center justify-between gap-2 text-xs">
                <div className="flex items-center gap-2">
                  <span className={`h-2 w-2 rounded-full ${severityDotClass(item.severity)}`} />
                  <span className="font-medium text-[var(--color-text-primary)]">{item.platform_number}</span>
                  <span className="text-[var(--color-text-secondary)]">{item.variable}</span>
                </div>
                <span className="text-[var(--color-text-muted)]">{new Date(item.detected_at).toLocaleDateString()}</span>
              </div>

              <div className="mt-1 line-clamp-2 text-xs text-[var(--color-text-secondary)]">{item.description}</div>

              <div className="mt-1 text-[10px] text-[var(--color-text-muted)]">
                {item.is_reviewed ? "Reviewed" : "Unreviewed"}
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import AnomalyComparisonChart from "@/components/anomaly/AnomalyComparisonChart";
import { getAnomalyDetail, markAnomalyReviewed } from "@/lib/anomalyQueries";
import type { AnomalyDetail } from "@/types/anomaly";

interface AnomalyDetailPanelProps {
  anomalyId: string;
  onClose?: () => void;
  onReviewed?: (anomalyId: string) => void;
}

function severityClass(severity: string): string {
  if (severity === "high") return "bg-[var(--color-coral)] text-[var(--color-text-inverse)]";
  if (severity === "medium") return "bg-[var(--color-sand)] text-[var(--color-ocean-deep)]";
  return "bg-[var(--color-seafoam)] text-[var(--color-ocean-deep)]";
}

function toDateLabel(value: string | null): string {
  if (!value) return "Unknown date";
  return new Date(value).toLocaleString();
}

export default function AnomalyDetailPanel({ anomalyId, onClose, onReviewed }: AnomalyDetailPanelProps) {
  const router = useRouter();
  const [detail, setDetail] = useState<AnomalyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [marking, setMarking] = useState(false);

  const loadDetail = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await getAnomalyDetail(anomalyId);
      setDetail(payload);
    } catch {
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }, [anomalyId]);

  useEffect(() => {
    void loadDetail();
  }, [loadDetail]);

  const prefillQuery = useMemo(() => {
    if (!detail) return "";
    const dateText = detail.profile_timestamp
      ? new Date(detail.profile_timestamp).toISOString().split("T")[0]
      : "this profile";
    return `analyze ${detail.variable} anomaly for float ${detail.platform_number} on ${dateText}`;
  }, [detail]);

  const handleReview = useCallback(async () => {
    if (!detail || detail.is_reviewed || marking) return;
    setMarking(true);
    try {
      await markAnomalyReviewed(detail.anomaly_id);
      await loadDetail();
      onReviewed?.(detail.anomaly_id);
    } finally {
      setMarking(false);
    }
  }, [detail, loadDetail, marking, onReviewed]);

  if (loading) {
    return (
      <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4 text-sm text-[var(--color-text-secondary)]">
        Loading anomaly details…
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4 text-sm text-[var(--color-text-secondary)]">
        Unable to load anomaly details.
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
      <div className="mb-3 flex items-start justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Anomaly Detail</h2>
          <div className="mt-1 flex items-center gap-2 text-xs">
            <span className={`rounded-full px-2 py-0.5 font-medium ${severityClass(detail.severity)}`}>
              {detail.severity}
            </span>
            <span className="rounded-full bg-[var(--color-bg-subtle)] px-2 py-0.5 text-[var(--color-text-secondary)]">
              {detail.anomaly_type}
            </span>
            {detail.is_reviewed ? (
              <span className="rounded-full bg-[var(--color-seafoam)] px-2 py-0.5 text-[var(--color-ocean-deep)]">
                Reviewed
              </span>
            ) : (
              <span className="rounded-full bg-[var(--color-bg-elevated)] px-2 py-0.5 text-[var(--color-text-secondary)]">
                Unreviewed
              </span>
            )}
          </div>
        </div>

        {onClose ? (
          <button
            onClick={onClose}
            className="rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-[var(--color-bg-subtle)]"
          >
            Close
          </button>
        ) : null}
      </div>

      <div className="grid gap-3 text-xs text-[var(--color-text-secondary)] md:grid-cols-2">
        <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-3">
          <div className="font-medium text-[var(--color-text-primary)]">Float</div>
          <div className="mt-1">{detail.platform_number}</div>
          <div>{detail.float_type ?? "unknown type"}</div>
          <div>{detail.country ?? "unknown country"}</div>
        </div>

        <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-3">
          <div className="font-medium text-[var(--color-text-primary)]">Profile</div>
          <div className="mt-1">{toDateLabel(detail.profile_timestamp)}</div>
          <div>
            {detail.profile_latitude?.toFixed(3) ?? "?"}, {detail.profile_longitude?.toFixed(3) ?? "?"}
          </div>
          <div>{detail.region ?? "region unavailable"}</div>
        </div>
      </div>

      <div className="mt-3">
        <AnomalyComparisonChart
          variable={detail.variable}
          baselineValue={detail.baseline_comparison.baseline_value}
          observedValue={detail.baseline_comparison.observed_value}
          deviationPercent={detail.baseline_comparison.deviation_percent}
        />
      </div>

      <div className="mt-3 rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-3 text-sm text-[var(--color-text-primary)]">
        {detail.description}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          onClick={() => router.push(`/chat?prefill=${encodeURIComponent(prefillQuery)}`)}
          className="rounded-md bg-[var(--color-ocean-primary)] px-3 py-2 text-xs font-medium text-[var(--color-text-inverse)]"
        >
          Investigate in Chat
        </button>
        <button
          onClick={handleReview}
          disabled={detail.is_reviewed || marking}
          className="rounded-md border border-[var(--color-border-default)] px-3 py-2 text-xs text-[var(--color-text-secondary)] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {detail.is_reviewed ? "Reviewed" : marking ? "Marking..." : "Mark as Reviewed"}
        </button>
      </div>
    </div>
  );
}

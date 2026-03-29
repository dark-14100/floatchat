"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";

import IngestionJobsTable from "@/components/admin/IngestionJobsTable";
import {
  getAdminIngestionSummary,
  getAdminIngestionTrend,
  type AdminIngestionSummaryResponse,
  type AdminIngestionTrendPoint,
} from "@/lib/adminQueries";

const Plot = dynamic(() => import("react-plotly.js"), {
  ssr: false,
  loading: () => <div className="py-8 text-center text-xs text-[var(--color-text-secondary)]">Loading chart...</div>,
});

function formatDuration(seconds: number | null): string {
  if (seconds === null) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

function MetricCard({ label, value, helper }: { label: string; value: string; helper?: string }) {
  return (
    <div className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <p className="text-[11px] uppercase tracking-wide text-[var(--color-text-muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-[var(--color-text-primary)]">{value}</p>
      {helper ? <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{helper}</p> : null}
    </div>
  );
}

export default function AdminIngestionJobsPage() {
  const searchParams = useSearchParams();
  const focusJobId = searchParams.get("focusJob");
  const [trendDays, setTrendDays] = useState(7);
  const [summary, setSummary] = useState<AdminIngestionSummaryResponse | null>(null);
  const [trend, setTrend] = useState<AdminIngestionTrendPoint[]>([]);
  const [loadingHealth, setLoadingHealth] = useState(true);
  const [healthError, setHealthError] = useState<string | null>(null);

  const fetchHealth = useCallback(async () => {
    setLoadingHealth(true);
    setHealthError(null);
    try {
      const [summaryResult, trendResult] = await Promise.all([
        getAdminIngestionSummary(),
        getAdminIngestionTrend(trendDays),
      ]);
      setSummary(summaryResult);
      setTrend(trendResult.trend);
    } catch (err: unknown) {
      setHealthError(err instanceof Error ? err.message : "Failed to load ingestion health data.");
    } finally {
      setLoadingHealth(false);
    }
  }, [trendDays]);

  useEffect(() => {
    void fetchHealth();
  }, [fetchHealth]);

  const trendDates = useMemo(() => trend.map((point) => point.date_utc), [trend]);
  const trendProfiles = useMemo(() => trend.map((point) => point.profiles_ingested), [trend]);
  const trendFailed = useMemo(() => trend.map((point) => point.failed_jobs), [trend]);
  const trendFailedRate = useMemo(() => trend.map((point) => point.failed_job_rate_pct), [trend]);

  return (
    <div className="space-y-4 p-4 md:p-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Ingestion Monitoring</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">Track all ingestion jobs in real time and retry failed jobs.</p>
      </div>

      <section className="space-y-3 rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Ingestion Health</h2>
            <p className="text-xs text-[var(--color-text-secondary)]">UTC aggregates for operations and alert verification.</p>
          </div>
          <button
            type="button"
            onClick={() => void fetchHealth()}
            className="rounded-md border border-[var(--color-border-default)] px-3 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-surface)]"
          >
            Refresh Health
          </button>
        </div>

        {healthError ? <p className="text-xs text-[var(--color-coral)]">{healthError}</p> : null}

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard
            label="Profiles Ingested Today"
            value={loadingHealth || !summary ? "..." : String(summary.total_profiles_ingested)}
            helper={summary ? `UTC day ${summary.date_utc}` : undefined}
          />
          <MetricCard
            label="New Floats Today"
            value={loadingHealth || !summary ? "..." : String(summary.new_floats_discovered)}
            helper="Unique platform discoveries"
          />
          <MetricCard
            label="Failed Jobs Today"
            value={loadingHealth || !summary ? "..." : String(summary.failed_jobs_count)}
            helper={summary && summary.failed_jobs.length > 0 ? summary.failed_jobs.slice(0, 2).join(", ") : "No failures logged"}
          />
          <MetricCard
            label="Avg Ingestion Duration"
            value={loadingHealth || !summary ? "..." : formatDuration(summary.average_ingestion_duration_seconds)}
            helper="Completed jobs only"
          />
        </div>

        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
            <h3 className="mb-2 text-sm font-medium text-[var(--color-text-primary)]">7-Day Ingestion Volume</h3>
            <Plot
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Profiles ingested",
                  x: trendDates,
                  y: trendProfiles,
                  line: { color: "#0ea5e9", width: 3 },
                  marker: { size: 7 },
                },
                {
                  type: "bar",
                  name: "Failed jobs",
                  x: trendDates,
                  y: trendFailed,
                  marker: { color: "#f97316", opacity: 0.7 },
                  yaxis: "y2",
                },
              ]}
              layout={{
                autosize: true,
                height: 300,
                margin: { l: 40, r: 40, t: 10, b: 35 },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                xaxis: { tickfont: { size: 10 } },
                yaxis: { title: { text: "Profiles" } },
                yaxis2: { title: { text: "Failed jobs" }, overlaying: "y", side: "right" },
                legend: { orientation: "h", y: 1.15, x: 0 },
              }}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: "100%" }}
            />
          </div>

          <div className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
            <h3 className="mb-2 text-sm font-medium text-[var(--color-text-primary)]">Failed Job Rate (%)</h3>
            <Plot
              data={[
                {
                  type: "scatter",
                  mode: "lines+markers",
                  name: "Failed rate",
                  x: trendDates,
                  y: trendFailedRate,
                  line: { color: "#ef4444", width: 3, shape: "spline" },
                  fill: "tozeroy",
                  fillcolor: "rgba(239,68,68,0.15)",
                  marker: { size: 7 },
                },
              ]}
              layout={{
                autosize: true,
                height: 300,
                margin: { l: 40, r: 20, t: 10, b: 35 },
                paper_bgcolor: "transparent",
                plot_bgcolor: "transparent",
                xaxis: { tickfont: { size: 10 } },
                yaxis: { title: { text: "Failed %" }, rangemode: "tozero" },
              }}
              config={{ displayModeBar: false, responsive: true }}
              style={{ width: "100%" }}
            />
          </div>
        </div>

        {summary ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3 text-xs text-[var(--color-text-secondary)]">
              <p className="mb-1 font-medium text-[var(--color-text-primary)]">Source Breakdown</p>
              <p>Manual upload jobs: {summary.source_breakdown.manual_upload ?? 0}</p>
              <p>GDAC sync jobs: {summary.source_breakdown.gdac_sync ?? 0}</p>
            </div>
            <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3 text-xs text-[var(--color-text-secondary)]">
              <p className="mb-1 font-medium text-[var(--color-text-primary)]">Failed Files Today</p>
              <p className="line-clamp-2">{summary.failed_jobs.length ? summary.failed_jobs.join(", ") : "None"}</p>
            </div>
          </div>
        ) : null}
      </section>

      <IngestionJobsTable
        focusJobId={focusJobId}
        initialDays={trendDays}
        onDaysChange={setTrendDays}
      />
    </div>
  );
}

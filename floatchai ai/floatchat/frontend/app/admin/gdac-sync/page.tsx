"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import {
  getGDACSyncRunDetail,
  listGDACSyncRuns,
  triggerGDACSync,
  type GDACSyncRun,
  type GDACSyncStatus,
} from "@/lib/adminQueries";

type StatusFilter = "all" | GDACSyncStatus;

function statusBadgeClass(status: GDACSyncStatus): string {
  if (status === "completed") return "bg-[var(--color-seafoam)]/20 text-[var(--color-seafoam)]";
  if (status === "failed") return "bg-[var(--color-coral)]/20 text-[var(--color-coral)]";
  if (status === "running") return "bg-[var(--color-ocean-primary)]/20 text-[var(--color-ocean-primary)]";
  return "bg-[var(--color-sand)]/20 text-[var(--color-sand)]";
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function toErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.body) as { detail?: string };
      if (typeof parsed.detail === "string" && parsed.detail) {
        return parsed.detail;
      }
    } catch {
      // Fall through to generic message.
    }
    return `Request failed (${err.status}).`;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return "Request failed.";
}

export default function AdminGDACSyncPage() {
  const [runs, setRuns] = useState<GDACSyncRun[]>([]);
  const [total, setTotal] = useState(0);
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [days, setDays] = useState(30);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [detail, setDetail] = useState<GDACSyncRun | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [triggering, setTriggering] = useState(false);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);

  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  const loadRuns = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await listGDACSyncRuns({
        days,
        limit,
        offset,
        status: statusFilter === "all" ? undefined : statusFilter,
      });

      setRuns(result.runs);
      setTotal(result.total);
      setSelectedRunId((prev) => {
        if (prev && result.runs.some((run) => run.run_id === prev)) {
          return prev;
        }
        return result.runs[0]?.run_id ?? null;
      });
    } catch (err: unknown) {
      setError(toErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [days, limit, offset, statusFilter]);

  useEffect(() => {
    void loadRuns();
  }, [loadRuns]);

  useEffect(() => {
    if (!selectedRunId) {
      setDetail(null);
      setDetailError(null);
      return;
    }

    let active = true;
    const loadDetail = async () => {
      setDetailLoading(true);
      setDetailError(null);
      try {
        const row = await getGDACSyncRunDetail(selectedRunId);
        if (!active) return;
        setDetail(row);
      } catch (err: unknown) {
        if (!active) return;
        setDetailError(toErrorMessage(err));
      } finally {
        if (!active) return;
        setDetailLoading(false);
      }
    };

    void loadDetail();
    return () => {
      active = false;
    };
  }, [selectedRunId]);

  const handleTrigger = async () => {
    setTriggering(true);
    setTriggerMessage(null);
    setError(null);

    try {
      const result = await triggerGDACSync();
      setTriggerMessage(`Sync queued (task: ${result.run_id.slice(0, 8)}...).`);
      await loadRuns();
    } catch (err: unknown) {
      setError(toErrorMessage(err));
    } finally {
      setTriggering(false);
    }
  };

  const summary = useMemo(() => {
    const completed = runs.filter((r) => r.status === "completed").length;
    const partial = runs.filter((r) => r.status === "partial").length;
    const failed = runs.filter((r) => r.status === "failed").length;
    const running = runs.filter((r) => r.status === "running").length;
    return { completed, partial, failed, running };
  }, [runs]);

  return (
    <div className="space-y-4 p-4 md:p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">GDAC Sync History</h1>
          <p className="text-sm text-[var(--color-text-secondary)]">Inspect scheduled/manual runs and trigger an on-demand sync.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="button" variant="outline" size="sm" disabled={loading} onClick={() => void loadRuns()}>
            Refresh
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={triggering} onClick={() => void handleTrigger()}>
            {triggering ? "Queueing..." : "Trigger Sync Now"}
          </Button>
        </div>
      </div>

      {error ? <p className="text-xs text-[var(--color-coral)]">{error}</p> : null}
      {triggerMessage ? <p className="text-xs text-[var(--color-seafoam)]">{triggerMessage}</p> : null}

      <div className="grid gap-3 md:grid-cols-4">
        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Completed</p>
          <p className="mt-1 text-xl font-semibold text-[var(--color-text-primary)]">{summary.completed}</p>
        </article>
        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Partial</p>
          <p className="mt-1 text-xl font-semibold text-[var(--color-text-primary)]">{summary.partial}</p>
        </article>
        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Failed</p>
          <p className="mt-1 text-xl font-semibold text-[var(--color-text-primary)]">{summary.failed}</p>
        </article>
        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Running</p>
          <p className="mt-1 text-xl font-semibold text-[var(--color-text-primary)]">{summary.running}</p>
        </article>
      </div>

      <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          <select
            value={statusFilter}
            onChange={(e) => {
              setOffset(0);
              setStatusFilter(e.target.value as StatusFilter);
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            <option value="all">All statuses</option>
            <option value="running">Running</option>
            <option value="completed">Completed</option>
            <option value="partial">Partial</option>
            <option value="failed">Failed</option>
          </select>

          <select
            value={days}
            onChange={(e) => {
              setOffset(0);
              setDays(Number(e.target.value));
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </div>

        <div className="overflow-x-auto rounded-lg border border-[var(--color-border-subtle)]">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-[var(--color-bg-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">Started</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Found</th>
                <th className="px-3 py-2">Downloaded</th>
                <th className="px-3 py-2">Ingested</th>
                <th className="px-3 py-2">Skipped</th>
                <th className="px-3 py-2">Duration (s)</th>
                <th className="px-3 py-2">Trigger</th>
                <th className="px-3 py-2">Mirror</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((run) => {
                const selected = run.run_id === selectedRunId;
                return (
                  <tr
                    key={run.run_id}
                    onClick={() => setSelectedRunId(run.run_id)}
                    className={[
                      "cursor-pointer border-t border-[var(--color-border-subtle)]",
                      selected ? "bg-[var(--color-ocean-lighter)]" : "hover:bg-[var(--color-bg-elevated)]",
                    ].join(" ")}
                  >
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{formatDate(run.started_at)}</td>
                    <td className="px-3 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(run.status)}`}>{run.status}</span>
                    </td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.index_profiles_found ?? 0}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.profiles_downloaded ?? 0}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.profiles_ingested ?? 0}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.profiles_skipped ?? 0}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.duration_seconds?.toFixed(1) ?? "-"}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.triggered_by}</td>
                    <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{run.gdac_mirror || "-"}</td>
                  </tr>
                );
              })}

              {!loading && runs.length === 0 ? (
                <tr>
                  <td colSpan={9} className="px-3 py-6 text-center text-sm text-[var(--color-text-secondary)]">
                    No GDAC sync runs found.
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>

        <div className="mt-3 flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
          <span>
            Showing {runs.length === 0 ? 0 : offset + 1} - {Math.min(offset + runs.length, total)} of {total}
          </span>
          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" disabled={!canPrev} onClick={() => setOffset(Math.max(0, offset - limit))}>
              Previous
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={!canNext} onClick={() => setOffset(offset + limit)}>
              Next
            </Button>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Run Detail</h2>
        {detailLoading ? <p className="mt-2 text-xs text-[var(--color-text-secondary)]">Loading run detail...</p> : null}
        {detailError ? <p className="mt-2 text-xs text-[var(--color-coral)]">{detailError}</p> : null}

        {!detailLoading && !detailError && !detail ? (
          <p className="mt-2 text-xs text-[var(--color-text-secondary)]">Select a run to inspect details.</p>
        ) : null}

        {!detailLoading && !detailError && detail ? (
          <div className="mt-3 grid gap-2 text-xs text-[var(--color-text-secondary)] md:grid-cols-2">
            <p><span className="font-medium text-[var(--color-text-primary)]">Run ID:</span> {detail.run_id}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Status:</span> {detail.status}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Started:</span> {formatDate(detail.started_at)}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Completed:</span> {formatDate(detail.completed_at)}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Mirror:</span> {detail.gdac_mirror || "-"}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Trigger:</span> {detail.triggered_by}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Profiles found:</span> {detail.index_profiles_found ?? 0}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Profiles downloaded:</span> {detail.profiles_downloaded ?? 0}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Profiles ingested:</span> {detail.profiles_ingested ?? 0}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Profiles skipped:</span> {detail.profiles_skipped ?? 0}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Lookback days:</span> {detail.lookback_days}</p>
            <p><span className="font-medium text-[var(--color-text-primary)]">Duration (s):</span> {detail.duration_seconds?.toFixed(1) ?? "-"}</p>
            <p className="md:col-span-2"><span className="font-medium text-[var(--color-text-primary)]">Error:</span> {detail.error_message || "-"}</p>
          </div>
        ) : null}
      </section>
    </div>
  );
}

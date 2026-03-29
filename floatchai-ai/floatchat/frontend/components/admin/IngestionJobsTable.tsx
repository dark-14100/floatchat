"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  createAdminIngestionStream,
  listAdminIngestionJobs,
  retryAdminIngestionJob,
  type AdminIngestionJob,
  type AdminIngestionSource,
  type AdminIngestionStatus,
  type AdminIngestionStreamPayload,
} from "@/lib/adminQueries";

type ReviewedStatus = "all" | AdminIngestionStatus;
type ReviewedSource = "all" | AdminIngestionSource;

interface IngestionJobsTableProps {
  focusJobId?: string | null;
  initialDays?: number;
  onDaysChange?: (days: number) => void;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function statusBadgeClass(status: AdminIngestionStatus): string {
  if (status === "succeeded") return "bg-[var(--color-seafoam)]/20 text-[var(--color-seafoam)]";
  if (status === "failed") return "bg-[var(--color-coral)]/20 text-[var(--color-coral)]";
  if (status === "running") return "bg-[var(--color-ocean-primary)]/20 text-[var(--color-ocean-primary)]";
  return "bg-[var(--color-sand)]/20 text-[var(--color-sand)]";
}

function toIngestionJob(payload: AdminIngestionStreamPayload): AdminIngestionJob {
  return {
    job_id: payload.job_id,
    dataset_id: payload.dataset_id,
    dataset_name: payload.dataset_name,
    source: payload.source,
    original_filename: null,
    raw_file_path: null,
    status: payload.status,
    progress_pct: payload.progress_pct,
    profiles_total: null,
    profiles_ingested: payload.profiles_ingested,
    error_log: payload.error_message,
    errors: null,
    started_at: payload.updated_at,
    completed_at: payload.updated_at,
    created_at: payload.updated_at,
  };
}

export default function IngestionJobsTable({
  focusJobId,
  initialDays = 7,
  onDaysChange,
}: IngestionJobsTableProps) {
  const [jobs, setJobs] = useState<AdminIngestionJob[]>([]);
  const [total, setTotal] = useState(0);
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [days, setDays] = useState(initialDays);
  const [statusFilter, setStatusFilter] = useState<ReviewedStatus>("all");
  const [sourceFilter, setSourceFilter] = useState<ReviewedSource>("all");
  const [loading, setLoading] = useState(true);
  const [retryingJobId, setRetryingJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [streamInfo, setStreamInfo] = useState<string>("Connecting stream...");

  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await listAdminIngestionJobs({
        days,
        limit,
        offset,
        status: statusFilter === "all" ? undefined : statusFilter,
        source: sourceFilter === "all" ? undefined : sourceFilter,
      });
      setJobs(result.jobs);
      setTotal(result.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load ingestion jobs.");
    } finally {
      setLoading(false);
    }
  }, [days, limit, offset, sourceFilter, statusFilter]);

  useEffect(() => {
    void fetchJobs();
  }, [fetchJobs]);

  useEffect(() => {
    onDaysChange?.(days);
  }, [days, onDaysChange]);

  const matchesFilters = useCallback(
    (job: AdminIngestionJob) => {
      const statusOk = statusFilter === "all" || job.status === statusFilter;
      const sourceOk = sourceFilter === "all" || job.source === sourceFilter;
      return statusOk && sourceOk;
    },
    [sourceFilter, statusFilter],
  );

  useEffect(() => {
    const stream = createAdminIngestionStream({
      onJobUpdate: (payload) => {
        setStreamInfo(`Live stream active · ${new Date().toLocaleTimeString()}`);
        setJobs((prev) => {
          const idx = prev.findIndex((job) => job.job_id === payload.job_id);
          if (idx >= 0) {
            const next = [...prev];
            const merged = {
              ...next[idx],
              status: payload.status,
              source: payload.source,
              progress_pct: payload.progress_pct,
              profiles_ingested: payload.profiles_ingested,
              error_log: payload.error_message,
              completed_at: payload.updated_at ?? next[idx].completed_at,
              started_at: payload.updated_at ?? next[idx].started_at,
              dataset_name: payload.dataset_name ?? next[idx].dataset_name,
            };

            if (!matchesFilters(merged)) {
              next.splice(idx, 1);
              return next;
            }

            next[idx] = merged;
            return next;
          }

          if (offset !== 0) {
            return prev;
          }

          const incoming = toIngestionJob(payload);
          if (!matchesFilters(incoming)) {
            return prev;
          }

          return [incoming, ...prev].slice(0, limit);
        });
      },
      onHeartbeat: () => {
        setStreamInfo(`Live stream active · ${new Date().toLocaleTimeString()}`);
      },
      onError: (streamError) => {
        setStreamInfo(`Stream issue: ${streamError.message}`);
      },
    });

    return () => {
      stream.abort();
    };
  }, [limit, matchesFilters, offset]);

  const handleRetry = async (jobId: string) => {
    setRetryingJobId(jobId);
    setError(null);

    try {
      await retryAdminIngestionJob(jobId);
      await fetchJobs();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Retry failed.");
    } finally {
      setRetryingJobId(null);
    }
  };

  const rows = useMemo(() => jobs, [jobs]);

  return (
    <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Ingestion Jobs</h2>
          <p className="text-xs text-[var(--color-text-secondary)]">{loading ? "Loading..." : `${total} jobs`} · {streamInfo}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <select
            value={statusFilter}
            onChange={(e) => {
              setOffset(0);
              setStatusFilter(e.target.value as ReviewedStatus);
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            <option value="all">All statuses</option>
            <option value="pending">Pending</option>
            <option value="running">Running</option>
            <option value="succeeded">Succeeded</option>
            <option value="failed">Failed</option>
          </select>

          <select
            value={sourceFilter}
            onChange={(e) => {
              setOffset(0);
              setSourceFilter(e.target.value as ReviewedSource);
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            <option value="all">All sources</option>
            <option value="manual_upload">Manual upload</option>
            <option value="gdac_sync">GDAC sync</option>
          </select>

          <select
            value={days}
            onChange={(e) => {
              setOffset(0);
              const nextDays = Number(e.target.value);
              setDays(nextDays);
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            <option value={1}>Last 1 day</option>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
          </select>
        </div>
      </div>

      {error ? <p className="mb-2 text-xs text-[var(--color-coral)]">{error}</p> : null}

      <div className="overflow-x-auto rounded-lg border border-[var(--color-border-subtle)]">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-[var(--color-bg-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
            <tr>
              <th className="px-3 py-2">Job</th>
              <th className="px-3 py-2">Dataset</th>
              <th className="px-3 py-2">Source</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2">Progress</th>
              <th className="px-3 py-2">Profiles</th>
              <th className="px-3 py-2">Error</th>
              <th className="px-3 py-2">Created</th>
              <th className="px-3 py-2">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((job) => {
              const focused = !!focusJobId && job.job_id === focusJobId;
              return (
                <tr
                  key={job.job_id}
                  className={[
                    "border-t border-[var(--color-border-subtle)]",
                    focused ? "bg-[var(--color-ocean-lighter)]" : "",
                  ].join(" ")}
                >
                  <td className="px-3 py-2 font-mono text-xs text-[var(--color-text-primary)]">{job.job_id.slice(0, 8)}...</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{job.dataset_name || job.dataset_id || "-"}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{job.source}</td>
                  <td className="px-3 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(job.status)}`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="w-24 rounded bg-[var(--color-bg-elevated)]">
                      <div
                        className="h-2 rounded bg-[var(--color-ocean-primary)]"
                        style={{ width: `${Math.max(0, Math.min(100, job.progress_pct))}%` }}
                      />
                    </div>
                  </td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">
                    {job.profiles_ingested}{job.profiles_total ? `/${job.profiles_total}` : ""}
                  </td>
                  <td className="max-w-[220px] px-3 py-2 text-xs text-[var(--color-text-secondary)]">
                    <span className="line-clamp-2">{job.error_log || "-"}</span>
                  </td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{formatDate(job.created_at)}</td>
                  <td className="px-3 py-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={job.status !== "failed" || retryingJobId === job.job_id}
                      onClick={() => void handleRetry(job.job_id)}
                    >
                      {retryingJobId === job.job_id ? "Retrying..." : "Retry"}
                    </Button>
                  </td>
                </tr>
              );
            })}

            {!loading && rows.length === 0 ? (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-sm text-[var(--color-text-secondary)]">
                  No ingestion jobs found.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
        <span>
          Showing {rows.length === 0 ? 0 : offset + 1} - {Math.min(offset + rows.length, total)} of {total}
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
  );
}

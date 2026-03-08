"use client";

import { useEffect, useMemo, useState } from "react";

import { getUnreviewedAnomalyCount } from "@/lib/anomalyQueries";
import { listAdminDatasets, listAdminIngestionJobs, type AdminIngestionJob } from "@/lib/adminQueries";

function toLocal(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export default function AdminOverviewPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [totalDatasets, setTotalDatasets] = useState(0);
  const [activeDatasets, setActiveDatasets] = useState(0);
  const [deletedDatasets, setDeletedDatasets] = useState(0);

  const [jobs, setJobs] = useState<AdminIngestionJob[]>([]);
  const [unreviewedAnomalies, setUnreviewedAnomalies] = useState(0);

  useEffect(() => {
    let mounted = true;

    const load = async () => {
      setLoading(true);
      setError(null);

      try {
        const [datasetResult, jobsResult, anomalyCount] = await Promise.all([
          listAdminDatasets({ include_deleted: true, limit: 200, offset: 0 }),
          listAdminIngestionJobs({ days: 7, limit: 200, offset: 0 }),
          getUnreviewedAnomalyCount(7),
        ]);

        if (!mounted) return;

        setTotalDatasets(datasetResult.total);
        const active = datasetResult.datasets.filter((d) => d.deleted_at == null).length;
        setActiveDatasets(active);
        setDeletedDatasets(Math.max(0, datasetResult.total - active));

        setJobs(jobsResult.jobs);
        setUnreviewedAnomalies(anomalyCount);
      } catch (err: unknown) {
        if (!mounted) return;
        setError(err instanceof Error ? err.message : "Failed to load admin overview.");
      } finally {
        if (!mounted) return;
        setLoading(false);
      }
    };

    void load();

    return () => {
      mounted = false;
    };
  }, []);

  const stats = useMemo(() => {
    const running = jobs.filter((j) => j.status === "running").length;
    const failed = jobs.filter((j) => j.status === "failed").length;
    const succeeded = jobs.filter((j) => j.status === "succeeded").length;

    const lastCompleted = [...jobs]
      .filter((j) => j.status === "succeeded")
      .sort((a, b) => {
        const ta = new Date(a.completed_at || a.created_at || 0).getTime();
        const tb = new Date(b.completed_at || b.created_at || 0).getTime();
        return tb - ta;
      })[0];

    return {
      running,
      failed,
      succeeded,
      lastCompleted,
    };
  }, [jobs]);

  return (
    <div className="space-y-4 p-4 md:p-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Admin Dashboard</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">Operational snapshot for datasets, ingestion, and anomalies.</p>
      </div>

      {error ? <p className="text-xs text-[var(--color-coral)]">{error}</p> : null}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Datasets</p>
          <p className="mt-1 text-2xl font-semibold text-[var(--color-text-primary)]">{loading ? "..." : totalDatasets}</p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{activeDatasets} active · {deletedDatasets} soft-deleted</p>
        </article>

        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Ingestion (7d)</p>
          <p className="mt-1 text-2xl font-semibold text-[var(--color-text-primary)]">{loading ? "..." : jobs.length}</p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{stats.succeeded} succeeded · {stats.failed} failed · {stats.running} running</p>
        </article>

        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Last Ingestion Completed</p>
          <p className="mt-1 text-sm font-medium text-[var(--color-text-primary)]">
            {loading ? "..." : stats.lastCompleted?.dataset_name || stats.lastCompleted?.job_id.slice(0, 8) || "-"}
          </p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">{loading ? "..." : toLocal(stats.lastCompleted?.completed_at || stats.lastCompleted?.created_at || null)}</p>
        </article>

        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">Unreviewed Anomalies (7d)</p>
          <p className="mt-1 text-2xl font-semibold text-[var(--color-text-primary)]">{loading ? "..." : unreviewedAnomalies}</p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">Review in anomaly feed for triage.</p>
        </article>

        <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">GDAC Sync</p>
          <p className="mt-1 text-sm font-medium text-[var(--color-text-primary)]">Not configured</p>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">Placeholder card for future auto-sync integration.</p>
        </article>
      </div>
    </div>
  );
}

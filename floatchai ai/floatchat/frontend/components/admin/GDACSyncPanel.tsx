"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  listGDACSyncRuns,
  triggerGDACSync,
  type GDACSyncRun,
  type GDACSyncStatus,
} from "@/lib/adminQueries";

import { Button } from "@/components/ui/button";

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

function nextScheduledRunUtcLabel(): string {
  const now = new Date();
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 1, 0, 0, 0));
  if (now.getTime() >= next.getTime()) {
    next.setUTCDate(next.getUTCDate() + 1);
  }
  return next.toLocaleString();
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

export default function GDACSyncPanel() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [triggerMessage, setTriggerMessage] = useState<string | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [latestRun, setLatestRun] = useState<GDACSyncRun | null>(null);

  const loadLatest = useCallback(async () => {
    setError(null);
    try {
      const result = await listGDACSyncRuns({ days: 30, limit: 1, offset: 0 });
      setLatestRun(result.runs[0] ?? null);
    } catch (err: unknown) {
      setError(toErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadLatest();
  }, [loadLatest]);

  const handleTrigger = async () => {
    setTriggering(true);
    setTriggerMessage(null);
    setError(null);

    try {
      const result = await triggerGDACSync();
      setTriggerMessage(`Sync queued (task: ${result.run_id.slice(0, 8)}...).`);
      await loadLatest();
    } catch (err: unknown) {
      setError(toErrorMessage(err));
    } finally {
      setTriggering(false);
    }
  };

  const statsText = useMemo(() => {
    if (!latestRun) return "No sync runs yet.";
    const ingested = latestRun.profiles_ingested ?? 0;
    const downloaded = latestRun.profiles_downloaded ?? 0;
    return `${ingested} ingested · ${downloaded} downloaded`;
  }, [latestRun]);

  return (
    <article className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide text-[var(--color-text-muted)]">GDAC Sync</p>
          <p className="mt-1 text-sm font-medium text-[var(--color-text-primary)]">
            {loading ? "Loading..." : latestRun ? "Configured" : "No runs yet"}
          </p>
        </div>
        {latestRun ? (
          <span className={`rounded-full px-2 py-0.5 text-xs ${statusBadgeClass(latestRun.status)}`}>
            {latestRun.status}
          </span>
        ) : null}
      </div>

      <div className="mt-2 space-y-1 text-xs text-[var(--color-text-secondary)]">
        <p>Last sync: {loading ? "..." : formatDate(latestRun?.started_at ?? null)}</p>
        <p>{loading ? "..." : statsText}</p>
        <p>Next scheduled run: {nextScheduledRunUtcLabel()} (local)</p>
      </div>

      {error ? <p className="mt-2 text-xs text-[var(--color-coral)]">{error}</p> : null}
      {triggerMessage ? <p className="mt-2 text-xs text-[var(--color-seafoam)]">{triggerMessage}</p> : null}

      <div className="mt-3 flex flex-wrap gap-2">
        <Button type="button" variant="outline" size="sm" onClick={() => void handleTrigger()} disabled={triggering}>
          {triggering ? "Queueing..." : "Trigger Sync Now"}
        </Button>
        <Link
          href="/admin/gdac-sync"
          className="inline-flex items-center rounded-md border border-[var(--color-border-default)] px-3 py-1.5 text-xs text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-elevated)] hover:text-[var(--color-text-primary)]"
        >
          View Run History
        </Link>
      </div>
    </article>
  );
}

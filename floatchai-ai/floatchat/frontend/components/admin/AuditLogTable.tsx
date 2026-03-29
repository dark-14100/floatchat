"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { listAdminAuditLog, type AdminAuditLogItem } from "@/lib/adminQueries";

const ACTION_OPTIONS = [
  "",
  "dataset_upload_started",
  "dataset_soft_deleted",
  "dataset_hard_deleted",
  "dataset_metadata_updated",
  "dataset_summary_regenerated",
  "dataset_visibility_changed",
  "ingestion_job_retried",
  "hard_delete_requested",
  "hard_delete_completed",
];

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export default function AuditLogTable() {
  const [logs, setLogs] = useState<AdminAuditLogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [limit] = useState(100);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [days, setDays] = useState(30);
  const [action, setAction] = useState("");
  const [entityType, setEntityType] = useState("");
  const [adminUserId, setAdminUserId] = useState("");

  const [expandedLogId, setExpandedLogId] = useState<string | null>(null);

  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  const fetchLogs = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await listAdminAuditLog({
        days,
        action: action || undefined,
        entity_type: entityType || undefined,
        admin_user_id: adminUserId.trim() || undefined,
        limit,
        offset,
      });
      setLogs(result.logs);
      setTotal(result.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load audit logs.");
    } finally {
      setLoading(false);
    }
  }, [action, adminUserId, days, entityType, limit, offset]);

  useEffect(() => {
    void fetchLogs();
  }, [fetchLogs]);

  return (
    <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Audit Log</h2>
          <p className="text-xs text-[var(--color-text-secondary)]">{loading ? "Loading..." : `${total} entries`}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          <select
            value={action}
            onChange={(e) => {
              setOffset(0);
              setAction(e.target.value);
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            {ACTION_OPTIONS.map((item) => (
              <option key={item || "all"} value={item}>
                {item || "All actions"}
              </option>
            ))}
          </select>

          <select
            value={entityType}
            onChange={(e) => {
              setOffset(0);
              setEntityType(e.target.value);
            }}
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          >
            <option value="">All entities</option>
            <option value="dataset">Dataset</option>
            <option value="ingestion_job">Ingestion job</option>
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

          <input
            value={adminUserId}
            onChange={(e) => {
              setOffset(0);
              setAdminUserId(e.target.value);
            }}
            placeholder="Admin user id"
            className="rounded border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-2 py-1 text-xs"
          />
        </div>
      </div>

      {error ? <p className="mb-2 text-xs text-[var(--color-coral)]">{error}</p> : null}

      <div className="overflow-x-auto rounded-lg border border-[var(--color-border-subtle)]">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-[var(--color-bg-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
            <tr>
              <th className="px-3 py-2">Timestamp</th>
              <th className="px-3 py-2">Admin</th>
              <th className="px-3 py-2">Action</th>
              <th className="px-3 py-2">Entity</th>
              <th className="px-3 py-2">Details</th>
            </tr>
          </thead>
          <tbody>
            {logs.map((log) => {
              const expanded = expandedLogId === log.log_id;
              const detailsString =
                log.details == null ? "-" : JSON.stringify(log.details, null, expanded ? 2 : 0);

              return (
                <tr key={log.log_id} className="border-t border-[var(--color-border-subtle)] align-top">
                  <td className="whitespace-nowrap px-3 py-2 text-xs text-[var(--color-text-secondary)]">{formatDate(log.created_at)}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{log.admin_user_email || log.admin_user_id || "-"}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-primary)]">{log.action}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{log.entity_type}:{log.entity_id}</td>
                  <td className="px-3 py-2">
                    <button
                      type="button"
                      onClick={() => setExpandedLogId(expanded ? null : log.log_id)}
                      className="text-left"
                    >
                      <pre className={[
                        "max-w-[360px] whitespace-pre-wrap break-all rounded bg-[var(--color-bg-elevated)] p-2 text-[10px] text-[var(--color-text-secondary)]",
                        expanded ? "" : "line-clamp-2",
                      ].join(" ")}
                      >
                        {detailsString}
                      </pre>
                    </button>
                  </td>
                </tr>
              );
            })}

            {!loading && logs.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-3 py-6 text-center text-sm text-[var(--color-text-secondary)]">
                  No audit entries found.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
        <span>
          Showing {logs.length === 0 ? 0 : offset + 1} - {Math.min(offset + logs.length, total)} of {total}
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

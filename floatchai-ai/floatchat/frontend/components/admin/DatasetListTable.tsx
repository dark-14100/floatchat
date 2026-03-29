"use client";

import { ArrowDownWideNarrow, ArrowUpNarrowWide, Eye, EyeOff } from "lucide-react";

import { Button } from "@/components/ui/button";
import type { AdminDataset } from "@/lib/adminQueries";

type SortField = "name" | "created_at" | "profile_count";
type SortDirection = "asc" | "desc";

interface DatasetListTableProps {
  datasets: AdminDataset[];
  loading: boolean;
  total: number;
  limit: number;
  offset: number;
  includeDeleted: boolean;
  sortBy: SortField;
  sortDirection: SortDirection;
  onIncludeDeletedChange: (next: boolean) => void;
  onSortChange: (field: SortField) => void;
  onOffsetChange: (nextOffset: number) => void;
  onSelectDataset: (datasetId: number) => void;
}

function asTagList(tags: unknown): string[] {
  if (Array.isArray(tags)) {
    return tags.filter((item): item is string => typeof item === "string");
  }
  return [];
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

function SortIcon({ active, direction }: { active: boolean; direction: SortDirection }) {
  if (!active) return <ArrowDownWideNarrow className="h-3.5 w-3.5 opacity-40" />;
  if (direction === "asc") return <ArrowUpNarrowWide className="h-3.5 w-3.5" />;
  return <ArrowDownWideNarrow className="h-3.5 w-3.5" />;
}

export default function DatasetListTable({
  datasets,
  loading,
  total,
  limit,
  offset,
  includeDeleted,
  sortBy,
  sortDirection,
  onIncludeDeletedChange,
  onSortChange,
  onOffsetChange,
  onSelectDataset,
}: DatasetListTableProps) {
  const canPrev = offset > 0;
  const canNext = offset + limit < total;

  return (
    <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Datasets</h2>
          <p className="text-xs text-[var(--color-text-secondary)]">{loading ? "Loading..." : `${total} total`}</p>
        </div>

        <Button
          type="button"
          variant="outline"
          onClick={() => onIncludeDeletedChange(!includeDeleted)}
          className="gap-2"
        >
          {includeDeleted ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          {includeDeleted ? "Hide Deleted" : "Show Deleted"}
        </Button>
      </div>

      <div className="overflow-x-auto rounded-lg border border-[var(--color-border-subtle)]">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-[var(--color-bg-elevated)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
            <tr>
              <th className="px-3 py-2">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSortChange("name")}>
                  Name <SortIcon active={sortBy === "name"} direction={sortDirection} />
                </button>
              </th>
              <th className="px-3 py-2">Visibility</th>
              <th className="px-3 py-2">Tags</th>
              <th className="px-3 py-2">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSortChange("profile_count")}>
                  Profiles <SortIcon active={sortBy === "profile_count"} direction={sortDirection} />
                </button>
              </th>
              <th className="px-3 py-2">Floats</th>
              <th className="px-3 py-2">Latest Job</th>
              <th className="px-3 py-2">
                <button type="button" className="inline-flex items-center gap-1" onClick={() => onSortChange("created_at")}>
                  Created <SortIcon active={sortBy === "created_at"} direction={sortDirection} />
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {datasets.map((dataset) => {
              const tags = asTagList(dataset.tags);
              const muted = dataset.deleted_at ? "opacity-60" : "";
              return (
                <tr
                  key={dataset.dataset_id}
                  className={`cursor-pointer border-t border-[var(--color-border-subtle)] hover:bg-[var(--color-bg-elevated)] ${muted}`}
                  onClick={() => onSelectDataset(dataset.dataset_id)}
                >
                  <td className="px-3 py-2">
                    <div className="font-medium text-[var(--color-text-primary)]">{dataset.name || dataset.source_filename || `Dataset ${dataset.dataset_id}`}</div>
                    <div className="text-xs text-[var(--color-text-secondary)]">{dataset.source_filename || "-"}</div>
                  </td>
                  <td className="px-3 py-2">
                    <span
                      className={[
                        "rounded-full px-2 py-0.5 text-xs",
                        dataset.is_public
                          ? "bg-[var(--color-seafoam)]/20 text-[var(--color-seafoam)]"
                          : "bg-[var(--color-coral)]/20 text-[var(--color-coral)]",
                      ].join(" ")}
                    >
                      {dataset.is_public ? "Public" : "Internal"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{tags.length ? tags.join(", ") : "-"}</td>
                  <td className="px-3 py-2 text-[var(--color-text-primary)]">{dataset.profile_count ?? 0}</td>
                  <td className="px-3 py-2 text-[var(--color-text-primary)]">{dataset.float_count ?? 0}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{dataset.latest_job_status ?? "-"}</td>
                  <td className="px-3 py-2 text-xs text-[var(--color-text-secondary)]">{formatDate(dataset.created_at)}</td>
                </tr>
              );
            })}

            {!loading && datasets.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-3 py-6 text-center text-sm text-[var(--color-text-secondary)]">
                  No datasets found.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>

      <div className="mt-3 flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
        <span>
          Showing {datasets.length === 0 ? 0 : offset + 1} - {Math.min(offset + datasets.length, total)} of {total}
        </span>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" disabled={!canPrev} onClick={() => onOffsetChange(Math.max(0, offset - limit))}>
            Previous
          </Button>
          <Button type="button" variant="outline" size="sm" disabled={!canNext} onClick={() => onOffsetChange(offset + limit)}>
            Next
          </Button>
        </div>
      </div>
    </section>
  );
}

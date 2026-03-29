"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import DatasetListTable from "@/components/admin/DatasetListTable";
import DatasetUploadPanel from "@/components/admin/DatasetUploadPanel";
import { listAdminDatasets, type AdminDataset, type UploadAcceptedResponse } from "@/lib/adminQueries";

type SortField = "name" | "created_at" | "profile_count";
type SortDirection = "asc" | "desc";

function compareNullableString(a: string | null, b: string | null): number {
  return (a || "").localeCompare(b || "");
}

function compareNullableNumber(a: number | null, b: number | null): number {
  return (a ?? 0) - (b ?? 0);
}

function sortDatasets(data: AdminDataset[], sortBy: SortField, sortDirection: SortDirection): AdminDataset[] {
  const sorted = [...data].sort((left, right) => {
    if (sortBy === "name") {
      return compareNullableString(left.name || left.source_filename, right.name || right.source_filename);
    }
    if (sortBy === "profile_count") {
      return compareNullableNumber(left.profile_count, right.profile_count);
    }

    const leftTs = new Date(left.created_at || 0).getTime();
    const rightTs = new Date(right.created_at || 0).getTime();
    return leftTs - rightTs;
  });

  if (sortDirection === "desc") {
    sorted.reverse();
  }

  return sorted;
}

export default function AdminDatasetsPage() {
  const router = useRouter();

  const [datasets, setDatasets] = useState<AdminDataset[]>([]);
  const [total, setTotal] = useState(0);
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [sortBy, setSortBy] = useState<SortField>("created_at");
  const [sortDirection, setSortDirection] = useState<SortDirection>("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDatasets = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const result = await listAdminDatasets({
        include_deleted: includeDeleted,
        limit,
        offset,
      });
      setDatasets(result.datasets);
      setTotal(result.total);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load datasets.");
    } finally {
      setLoading(false);
    }
  }, [includeDeleted, limit, offset]);

  useEffect(() => {
    void loadDatasets();
  }, [loadDatasets]);

  const sortedDatasets = useMemo(
    () => sortDatasets(datasets, sortBy, sortDirection),
    [datasets, sortBy, sortDirection],
  );

  const handleSortChange = (field: SortField) => {
    if (sortBy === field) {
      setSortDirection((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortBy(field);
    setSortDirection("asc");
  };

  const handleUploadAccepted = (result: UploadAcceptedResponse) => {
    void loadDatasets();
    router.push(`/admin/ingestion-jobs?focusJob=${encodeURIComponent(result.job_id)}`);
  };

  return (
    <div className="space-y-4 p-4 md:p-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">Dataset Management</h1>
        <p className="text-sm text-[var(--color-text-secondary)]">Upload files, inspect dataset metadata, and manage lifecycle actions.</p>
      </div>

      {error ? <p className="text-xs text-[var(--color-coral)]">{error}</p> : null}

      <DatasetUploadPanel onUploaded={handleUploadAccepted} />

      <DatasetListTable
        datasets={sortedDatasets}
        loading={loading}
        total={total}
        limit={limit}
        offset={offset}
        includeDeleted={includeDeleted}
        sortBy={sortBy}
        sortDirection={sortDirection}
        onIncludeDeletedChange={(next) => {
          setOffset(0);
          setIncludeDeleted(next);
        }}
        onSortChange={handleSortChange}
        onOffsetChange={setOffset}
        onSelectDataset={(datasetId) => router.push(`/admin/datasets/${datasetId}`)}
      />
    </div>
  );
}

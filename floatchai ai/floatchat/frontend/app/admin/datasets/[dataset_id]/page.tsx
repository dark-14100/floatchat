"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";

import DatasetDetailEditor from "@/components/admin/DatasetDetailEditor";
import {
  getAdminDatasetDetail,
  hardDeleteAdminDataset,
  patchAdminDatasetMetadata,
  regenerateAdminDatasetSummary,
  restoreAdminDataset,
  softDeleteAdminDataset,
  type AdminDatasetDetail,
  type AdminDatasetMetadataPatch,
} from "@/lib/adminQueries";

export default function AdminDatasetDetailPage() {
  const params = useParams<{ dataset_id: string }>();
  const datasetId = Number(params.dataset_id);

  const [dataset, setDataset] = useState<AdminDatasetDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDataset = useCallback(async () => {
    if (!Number.isFinite(datasetId) || datasetId <= 0) {
      setError("Invalid dataset id.");
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const detail = await getAdminDatasetDetail(datasetId);
      setDataset(detail);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load dataset detail.");
      setDataset(null);
    } finally {
      setLoading(false);
    }
  }, [datasetId]);

  useEffect(() => {
    void loadDataset();
  }, [loadDataset]);

  const saveMetadata = async (patch: AdminDatasetMetadataPatch): Promise<void> => {
    await patchAdminDatasetMetadata(datasetId, patch);
    await loadDataset();
  };

  const regenerateSummary = async (): Promise<string> => {
    const result = await regenerateAdminDatasetSummary(datasetId);
    await loadDataset();
    return result.task_id;
  };

  const softDelete = async (): Promise<void> => {
    await softDeleteAdminDataset(datasetId);
    await loadDataset();
  };

  const restore = async (): Promise<void> => {
    await restoreAdminDataset(datasetId);
    await loadDataset();
  };

  const hardDelete = async (confirmDatasetName: string): Promise<string> => {
    const result = await hardDeleteAdminDataset(datasetId, {
      confirm: true,
      confirm_dataset_name: confirmDatasetName,
    });
    await loadDataset();
    return result.task_id;
  };

  if (loading) {
    return <div className="p-5 text-sm text-[var(--color-text-secondary)]">Loading dataset...</div>;
  }

  if (error) {
    return <div className="p-5 text-sm text-[var(--color-coral)]">{error}</div>;
  }

  if (!dataset) {
    return <div className="p-5 text-sm text-[var(--color-text-secondary)]">Dataset not found.</div>;
  }

  return (
    <div className="space-y-4 p-4 md:p-5">
      <div>
        <h1 className="text-lg font-semibold text-[var(--color-text-primary)]">
          {dataset.name || dataset.source_filename || `Dataset ${dataset.dataset_id}`}
        </h1>
        <p className="text-sm text-[var(--color-text-secondary)]">Dataset ID: {dataset.dataset_id}</p>
      </div>

      <DatasetDetailEditor
        dataset={dataset}
        onSaveMetadata={saveMetadata}
        onRegenerateSummary={regenerateSummary}
        onSoftDelete={softDelete}
        onRestore={restore}
        onHardDelete={hardDelete}
      />
    </div>
  );
}

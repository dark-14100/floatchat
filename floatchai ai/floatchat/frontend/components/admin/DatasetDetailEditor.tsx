"use client";

import { useEffect, useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { AdminDatasetDetail, AdminDatasetMetadataPatch } from "@/lib/adminQueries";

interface DatasetDetailEditorProps {
  dataset: AdminDatasetDetail;
  onSaveMetadata: (patch: AdminDatasetMetadataPatch) => Promise<void>;
  onRegenerateSummary: () => Promise<string>;
  onSoftDelete: () => Promise<void>;
  onRestore: () => Promise<void>;
  onHardDelete: (confirmDatasetName: string) => Promise<string>;
}

function asTagList(tags: unknown): string[] {
  if (Array.isArray(tags)) {
    return tags.filter((item): item is string => typeof item === "string");
  }
  return [];
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function formatDate(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString();
}

export default function DatasetDetailEditor({
  dataset,
  onSaveMetadata,
  onRegenerateSummary,
  onSoftDelete,
  onRestore,
  onHardDelete,
}: DatasetDetailEditorProps) {
  const [name, setName] = useState(dataset.name ?? "");
  const [description, setDescription] = useState(dataset.description ?? "");
  const [tagsInput, setTagsInput] = useState(asTagList(dataset.tags).join(", "));
  const [isPublic, setIsPublic] = useState(dataset.is_public);

  const [saving, setSaving] = useState(false);
  const [regenerating, setRegenerating] = useState(false);
  const [softDeleting, setSoftDeleting] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [hardDeleting, setHardDeleting] = useState(false);

  const [softDeleteOpen, setSoftDeleteOpen] = useState(false);
  const [hardDeleteOpen, setHardDeleteOpen] = useState(false);
  const [hardDeleteName, setHardDeleteName] = useState("");

  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    setName(dataset.name ?? "");
    setDescription(dataset.description ?? "");
    setTagsInput(asTagList(dataset.tags).join(", "));
    setIsPublic(dataset.is_public);
  }, [dataset]);

  const parsedTags = useMemo(
    () =>
      tagsInput
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    [tagsInput],
  );

  const datasetLabel = dataset.name || dataset.source_filename || `Dataset ${dataset.dataset_id}`;

  const handleSave = async () => {
    setSaving(true);
    setStatusMessage(null);
    setErrorMessage(null);

    try {
      await onSaveMetadata({
        name: name.trim() || undefined,
        description: description.trim() || undefined,
        tags: parsedTags,
        is_public: isPublic,
      });
      setStatusMessage("Metadata saved.");
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to save metadata.");
    } finally {
      setSaving(false);
    }
  };

  const handleRegenerateSummary = async () => {
    setRegenerating(true);
    setStatusMessage(null);
    setErrorMessage(null);

    try {
      const taskId = await onRegenerateSummary();
      setStatusMessage(`Summary regeneration queued: ${taskId}`);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Failed to queue summary regeneration.");
    } finally {
      setRegenerating(false);
    }
  };

  const handleSoftDelete = async () => {
    setSoftDeleting(true);
    setStatusMessage(null);
    setErrorMessage(null);

    try {
      await onSoftDelete();
      setStatusMessage("Dataset soft-deleted.");
      setSoftDeleteOpen(false);
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Soft-delete failed.");
    } finally {
      setSoftDeleting(false);
    }
  };

  const handleRestore = async () => {
    setRestoring(true);
    setStatusMessage(null);
    setErrorMessage(null);

    try {
      await onRestore();
      setStatusMessage("Dataset restored.");
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Restore failed.");
    } finally {
      setRestoring(false);
    }
  };

  const handleHardDelete = async () => {
    setHardDeleting(true);
    setStatusMessage(null);
    setErrorMessage(null);

    try {
      const taskId = await onHardDelete(hardDeleteName);
      setStatusMessage(`Hard-delete queued: ${taskId}`);
      setHardDeleteOpen(false);
      setHardDeleteName("");
    } catch (err: unknown) {
      setErrorMessage(err instanceof Error ? err.message : "Hard-delete failed.");
    } finally {
      setHardDeleting(false);
    }
  };

  return (
    <div className="grid gap-4 p-4 md:grid-cols-[1.2fr_1fr] md:p-5">
      <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
        <h2 className="mb-3 text-base font-semibold text-[var(--color-text-primary)]">Metadata</h2>

        <div className="grid gap-3">
          <label className="grid gap-1">
            <span className="text-xs text-[var(--color-text-secondary)]">Name</span>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </label>

          <label className="grid gap-1">
            <span className="text-xs text-[var(--color-text-secondary)]">Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={5}
              className="rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-base)] px-3 py-2 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-ocean-primary)]"
            />
          </label>

          <label className="grid gap-1">
            <span className="text-xs text-[var(--color-text-secondary)]">Tags (comma-separated)</span>
            <Input value={tagsInput} onChange={(e) => setTagsInput(e.target.value)} />
          </label>

          <label className="flex items-center justify-between rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-base)] px-3 py-2">
            <span className="text-sm text-[var(--color-text-primary)]">Public visibility</span>
            <input
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
              className="h-4 w-4"
            />
          </label>

          <div className="flex flex-wrap gap-2">
            <Button type="button" onClick={handleSave} disabled={saving}>
              {saving ? "Saving..." : "Save Metadata"}
            </Button>
            <Button type="button" variant="outline" onClick={handleRegenerateSummary} disabled={regenerating}>
              {regenerating ? "Queueing..." : "Regenerate Summary"}
            </Button>
          </div>
        </div>

        {statusMessage ? <p className="mt-3 text-xs text-[var(--color-seafoam)]">{statusMessage}</p> : null}
        {errorMessage ? <p className="mt-3 text-xs text-[var(--color-coral)]">{errorMessage}</p> : null}
      </section>

      <section className="space-y-4">
        <div className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <h2 className="mb-3 text-base font-semibold text-[var(--color-text-primary)]">Dataset Stats</h2>
          <div className="grid gap-2 text-sm text-[var(--color-text-secondary)]">
            <p><span className="text-[var(--color-text-primary)]">Float count:</span> {dataset.float_count ?? 0}</p>
            <p><span className="text-[var(--color-text-primary)]">Profile count:</span> {dataset.profile_count ?? 0}</p>
            <p><span className="text-[var(--color-text-primary)]">Measurement count:</span> {dataset.measurement_count}</p>
            <p><span className="text-[var(--color-text-primary)]">Storage size:</span> {formatBytes(dataset.storage_size_bytes || 0)}</p>
            <p><span className="text-[var(--color-text-primary)]">Created:</span> {formatDate(dataset.created_at)}</p>
            <p><span className="text-[var(--color-text-primary)]">Deleted at:</span> {formatDate(dataset.deleted_at)}</p>
          </div>
        </div>

        <div className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <h2 className="mb-3 text-base font-semibold text-[var(--color-text-primary)]">Lifecycle Actions</h2>
          <div className="flex flex-wrap gap-2">
            {dataset.deleted_at ? (
              <Button type="button" variant="outline" onClick={handleRestore} disabled={restoring}>
                {restoring ? "Restoring..." : "Restore Dataset"}
              </Button>
            ) : (
              <Button type="button" variant="outline" onClick={() => setSoftDeleteOpen(true)}>
                Soft Delete
              </Button>
            )}
            <Button
              type="button"
              variant="outline"
              className="border-[var(--color-coral)] text-[var(--color-coral)] hover:bg-[var(--color-coral)]/10"
              onClick={() => setHardDeleteOpen(true)}
            >
              Hard Delete
            </Button>
          </div>
        </div>

        <div className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
          <h2 className="mb-2 text-base font-semibold text-[var(--color-text-primary)]">Current Summary</h2>
          <p className="whitespace-pre-wrap text-sm text-[var(--color-text-secondary)]">
            {dataset.summary_text || "No summary available."}
          </p>
        </div>
      </section>

      <Dialog open={softDeleteOpen} onOpenChange={setSoftDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Soft-delete dataset?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[var(--color-text-secondary)]">
            This removes <strong>{datasetLabel}</strong> from researcher-facing search while preserving underlying data.
          </p>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setSoftDeleteOpen(false)}>
              Cancel
            </Button>
            <Button type="button" onClick={handleSoftDelete} disabled={softDeleting}>
              {softDeleting ? "Applying..." : "Confirm Soft Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={hardDeleteOpen} onOpenChange={setHardDeleteOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Hard-delete dataset?</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-[var(--color-text-secondary)]">
            This permanently deletes dataset rows, ingestion jobs, profiles, measurements, and anomalies.
          </p>
          <label className="grid gap-1">
            <span className="text-xs text-[var(--color-text-secondary)]">Type dataset name to confirm</span>
            <Input
              value={hardDeleteName}
              onChange={(e) => setHardDeleteName(e.target.value)}
              placeholder={datasetLabel}
            />
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setHardDeleteOpen(false)}>
              Cancel
            </Button>
            <Button
              type="button"
              className="bg-[var(--color-coral)] text-[var(--color-text-inverse)] hover:bg-[var(--color-coral)]/90"
              onClick={handleHardDelete}
              disabled={hardDeleting || !hardDeleteName.trim()}
            >
              {hardDeleting ? "Queueing..." : "Queue Hard Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

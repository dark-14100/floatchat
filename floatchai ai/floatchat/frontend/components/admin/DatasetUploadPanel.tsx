"use client";

import { useMemo, useRef, useState } from "react";
import { UploadCloud, FileArchive, FileType } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { uploadDatasetFile, type UploadAcceptedResponse } from "@/lib/adminQueries";

interface DatasetUploadPanelProps {
  onUploaded: (result: UploadAcceptedResponse) => void;
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

function acceptsFile(file: File): boolean {
  const lower = file.name.toLowerCase();
  return lower.endsWith(".nc") || lower.endsWith(".nc4") || lower.endsWith(".zip");
}

export default function DatasetUploadPanel({ onUploaded }: DatasetUploadPanelProps) {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [datasetName, setDatasetName] = useState("");
  const [isDragging, setIsDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const fileTypeIcon = useMemo(() => {
    if (!selectedFile) return UploadCloud;
    if (selectedFile.name.toLowerCase().endsWith(".zip")) return FileArchive;
    return FileType;
  }, [selectedFile]);

  const FileIcon = fileTypeIcon;

  const pickFile = () => {
    fileInputRef.current?.click();
  };

  const handleFile = (file: File) => {
    setError(null);
    setMessage(null);
    if (!acceptsFile(file)) {
      setSelectedFile(null);
      setError("Only .nc, .nc4, and .zip files are accepted.");
      return;
    }
    setSelectedFile(file);
  };

  const handleUpload = async () => {
    if (!selectedFile || uploading) {
      return;
    }

    setUploading(true);
    setProgress(0);
    setError(null);
    setMessage(null);

    try {
      const result = await uploadDatasetFile(selectedFile, datasetName || undefined, setProgress);
      setMessage(`Accepted: ${result.message}`);
      setSelectedFile(null);
      setDatasetName("");
      setProgress(100);
      onUploaded(result);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setUploading(false);
    }
  };

  return (
    <section className="rounded-xl border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
      <div className="mb-3">
        <h2 className="text-base font-semibold text-[var(--color-text-primary)]">Upload Dataset</h2>
        <p className="text-xs text-[var(--color-text-secondary)]">Drag and drop .nc/.nc4/.zip files or browse to upload.</p>
      </div>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          if (!uploading) setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setIsDragging(false);
          if (uploading) return;
          const dropped = e.dataTransfer.files?.[0];
          if (dropped) {
            handleFile(dropped);
          }
        }}
        className={[
          "rounded-lg border border-dashed p-4 transition-colors",
          isDragging
            ? "border-[var(--color-ocean-primary)] bg-[var(--color-ocean-lighter)]"
            : "border-[var(--color-border-default)] bg-[var(--color-bg-base)]",
        ].join(" ")}
      >
        <input
          ref={fileInputRef}
          type="file"
          accept=".nc,.nc4,.zip"
          className="hidden"
          onChange={(e) => {
            const picked = e.target.files?.[0];
            if (picked) {
              handleFile(picked);
            }
          }}
        />

        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-3">
            <div className="rounded-md bg-[var(--color-bg-elevated)] p-2 text-[var(--color-text-secondary)]">
              <FileIcon className="h-4 w-4" />
            </div>
            <div>
              <p className="text-sm text-[var(--color-text-primary)]">
                {selectedFile ? selectedFile.name : "Drop a file here"}
              </p>
              <p className="text-xs text-[var(--color-text-secondary)]">
                {selectedFile ? formatFileSize(selectedFile.size) : "or click browse"}
              </p>
            </div>
          </div>

          <Button type="button" variant="outline" onClick={pickFile} disabled={uploading}>
            Browse
          </Button>
        </div>
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-[1fr_auto]">
        <Input
          value={datasetName}
          onChange={(e) => setDatasetName(e.target.value)}
          placeholder="Optional dataset name"
          disabled={uploading}
        />
        <Button type="button" onClick={handleUpload} disabled={!selectedFile || uploading}>
          {uploading ? "Uploading..." : "Upload"}
        </Button>
      </div>

      <div className="mt-3 h-2 overflow-hidden rounded bg-[var(--color-bg-elevated)]">
        <div
          className="h-full bg-[var(--color-ocean-primary)] transition-[width] duration-300"
          style={{ width: `${progress}%` }}
        />
      </div>

      {message ? <p className="mt-2 text-xs text-[var(--color-seafoam)]">{message}</p> : null}
      {error ? <p className="mt-2 text-xs text-[var(--color-coral)]">{error}</p> : null}
    </section>
  );
}

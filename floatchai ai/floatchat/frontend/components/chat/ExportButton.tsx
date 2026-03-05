"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Braces, Database, Download, FileText, Loader2 } from "lucide-react";

import { ApiError } from "@/lib/api";
import {
  createExport,
  downloadExportBlob,
  getExportStatus,
} from "@/lib/exportQueries";
import { useChatStore } from "@/store/chatStore";
import type { ExportFormat } from "@/types/export";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

interface ExportButtonProps {
  messageId: string;
  rowCount: number;
}

const POLL_INTERVAL_MS = 3000;
const MAX_POLL_ATTEMPTS = 40;

function parseExportError(error: unknown): string {
  if (error instanceof ApiError) {
    try {
      const parsed = JSON.parse(error.body) as {
        error?: string;
        detail?: string;
      };

      if (parsed.detail) {
        return parsed.detail;
      }
      if (parsed.error) {
        return parsed.error;
      }
    } catch {
      // Fall through to status-based message.
    }

    return `Export failed (${error.status}).`;
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Export failed. Please try again.";
}

function triggerUrlDownload(url: string): void {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
}

export default function ExportButton({ messageId, rowCount }: ExportButtonProps) {
  const rows = useChatStore((state) => state.resultRows[messageId] ?? []);

  const [isRequesting, setIsRequesting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const [pollTaskId, setPollTaskId] = useState<string | null>(null);
  const [pollAttempts, setPollAttempts] = useState(0);
  const [statusText, setStatusText] = useState<string>("");
  const [errorText, setErrorText] = useState<string>("");
  const [successText, setSuccessText] = useState<string>("");
  const [activeFormat, setActiveFormat] = useState<ExportFormat | null>(null);

  const isDisabled = isRequesting || isPolling;

  const activeFormatLabel = useMemo(() => {
    if (!activeFormat) return "export";
    if (activeFormat === "csv") return "CSV export";
    if (activeFormat === "netcdf") return "NetCDF export";
    return "JSON export";
  }, [activeFormat]);

  const clearInlineMessages = useCallback(() => {
    setStatusText("");
    setErrorText("");
    setSuccessText("");
  }, []);

  const handleExport = useCallback(
    async (format: ExportFormat) => {
      if (isDisabled) {
        return;
      }

      clearInlineMessages();
      setPollAttempts(0);
      setPollTaskId(null);
      setActiveFormat(format);

      if (rows.length === 0) {
        setErrorText("Export data has expired. Please re-run your query and try again.");
        return;
      }

      setIsRequesting(true);

      try {
        const result = await createExport({
          message_id: messageId,
          format,
          rows,
        });

        if (result.mode === "sync") {
          downloadExportBlob(result.blob, result.filename);
          setSuccessText("Download started.");
          return;
        }

        setPollTaskId(result.queued.task_id);
        setIsPolling(true);
        setStatusText("Preparing export...");
      } catch (error: unknown) {
        setErrorText(parseExportError(error));
      } finally {
        setIsRequesting(false);
      }
    },
    [clearInlineMessages, isDisabled, messageId, rows],
  );

  useEffect(() => {
    if (!isPolling || !pollTaskId) {
      return;
    }

    let cancelled = false;
    let timeoutId: number | null = null;
    let attempts = 0;

    const poll = async () => {
      if (cancelled) {
        return;
      }

      attempts += 1;
      setPollAttempts(attempts);

      if (attempts > MAX_POLL_ATTEMPTS) {
        setIsPolling(false);
        setErrorText("Export is taking longer than expected. Please try again.");
        setStatusText("");
        return;
      }

      try {
        const status = await getExportStatus(pollTaskId);

        if (cancelled) {
          return;
        }

        if (status.status === "queued") {
          setStatusText("Export queued...");
          timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS);
          return;
        }

        if (status.status === "processing") {
          setStatusText("Preparing export...");
          timeoutId = window.setTimeout(poll, POLL_INTERVAL_MS);
          return;
        }

        if (status.status === "complete") {
          setIsPolling(false);
          setPollTaskId(null);

          if (!status.download_url) {
            setStatusText("");
            setErrorText("Export completed but no download URL was returned.");
            return;
          }

          setStatusText("Export ready. Downloading...");
          triggerUrlDownload(status.download_url);
          setSuccessText("Export ready — download started.");

          timeoutId = window.setTimeout(() => {
            setStatusText("");
          }, 5000);
          return;
        }

        setIsPolling(false);
        setPollTaskId(null);
        setStatusText("");
        setErrorText(status.error || "Export failed. Please try again.");
      } catch (error: unknown) {
        if (cancelled) {
          return;
        }

        setIsPolling(false);
        setPollTaskId(null);
        setStatusText("");
        setErrorText(parseExportError(error));
      }
    };

    void poll();

    return () => {
      cancelled = true;
      if (timeoutId !== null) {
        window.clearTimeout(timeoutId);
      }
    };
  }, [isPolling, pollTaskId]);

  if (rowCount <= 0) {
    return null;
  }

  return (
    <div className="flex flex-col items-end gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button size="sm" variant="outline" disabled={isDisabled} className="gap-1.5">
            {isDisabled ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Download className="h-3.5 w-3.5" />
            )}
            {isPolling ? "Preparing..." : "Export"}
          </Button>
        </DropdownMenuTrigger>

        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuItem
            disabled={isDisabled}
            onSelect={(event) => {
              event.preventDefault();
              void handleExport("csv");
            }}
          >
            <FileText className="mr-2 h-4 w-4" />
            Export as CSV
          </DropdownMenuItem>

          <DropdownMenuItem
            disabled={isDisabled}
            onSelect={(event) => {
              event.preventDefault();
              void handleExport("netcdf");
            }}
          >
            <Database className="mr-2 h-4 w-4" />
            Export as NetCDF
          </DropdownMenuItem>

          <DropdownMenuItem
            disabled={isDisabled}
            onSelect={(event) => {
              event.preventDefault();
              void handleExport("json");
            }}
          >
            <Braces className="mr-2 h-4 w-4" />
            Export as JSON
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      {statusText && (
        <p className="text-right text-xs text-muted-foreground">
          {statusText}
          {isPolling ? ` (${pollAttempts}/${MAX_POLL_ATTEMPTS})` : ""}
        </p>
      )}

      {successText && (
        <p className="text-right text-xs text-muted-foreground">
          {successText}
        </p>
      )}

      {errorText && (
        <p className="text-right text-xs text-destructive">
          {activeFormatLabel}: {errorText}
        </p>
      )}
    </div>
  );
}

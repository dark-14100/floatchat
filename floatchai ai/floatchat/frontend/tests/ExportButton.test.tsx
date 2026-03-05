import React from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ExportButton from "@/components/chat/ExportButton";
import {
  createExport,
  downloadExportBlob,
  getExportStatus,
} from "@/lib/exportQueries";

type StoreShape = {
  resultRows: Record<string, Array<Record<string, unknown>>>;
};

let mockStoreState: StoreShape = {
  resultRows: {},
};

vi.mock("@/store/chatStore", () => ({
  useChatStore: (selector: (state: StoreShape) => unknown) => selector(mockStoreState),
}));

vi.mock("@/lib/exportQueries", () => ({
  createExport: vi.fn(),
  getExportStatus: vi.fn(),
  downloadExportBlob: vi.fn(),
}));

vi.mock("@/components/ui/dropdown-menu", () => ({
  DropdownMenu: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  DropdownMenuContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
  DropdownMenuItem: ({
    children,
    onSelect,
    disabled,
  }: {
    children: React.ReactNode;
    onSelect?: (event: React.MouseEvent<HTMLButtonElement>) => void;
    disabled?: boolean;
  }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={(event) => {
        onSelect?.(event);
      }}
    >
      {children}
    </button>
  ),
}));

describe("ExportButton", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.useRealTimers();

    mockStoreState = {
      resultRows: {
        "msg-1": [
          { profile_id: 1, pressure: 10, temperature: 25.1 },
          { profile_id: 2, pressure: 20, temperature: 24.7 },
        ],
      },
    };
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders nothing when rowCount is zero", () => {
    const { container } = render(<ExportButton messageId="msg-1" rowCount={0} />);
    expect(container.innerHTML).toBe("");
  });

  it("runs sync export and triggers blob download", async () => {
    vi.mocked(createExport).mockResolvedValue({
      mode: "sync",
      blob: new Blob(["csv-data"], { type: "text/csv" }),
      filename: "floatchat.csv",
      contentType: "text/csv",
    });

    render(<ExportButton messageId="msg-1" rowCount={2} />);

    fireEvent.click(screen.getByRole("button", { name: /export as csv/i }));

    await waitFor(() => {
      expect(createExport).toHaveBeenCalledTimes(1);
    });

    expect(downloadExportBlob).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Download started.")).toBeInTheDocument();
  });

  it("polls async export until complete and shows success", async () => {
    vi.useFakeTimers();

    vi.mocked(createExport).mockResolvedValue({
      mode: "async",
      queued: {
        task_id: "task-123",
        status: "queued",
        poll_url: "/api/v1/export/status/task-123",
      },
    });

    vi.mocked(getExportStatus)
      .mockResolvedValueOnce({ status: "queued", task_id: "task-123" })
      .mockResolvedValueOnce({ status: "processing", task_id: "task-123" })
      .mockResolvedValueOnce({
        status: "complete",
        task_id: "task-123",
        download_url: "https://example.com/file.csv",
        expires_at: "2026-01-01T00:00:00Z",
      });

    render(<ExportButton messageId="msg-1" rowCount={2} />);

    fireEvent.click(screen.getByRole("button", { name: /export as csv/i }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(screen.getByText(/Export queued/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
    });

    expect(screen.getByText(/Preparing export/i)).toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(3000);
      await Promise.resolve();
    });

    expect(screen.getByText("Export ready — download started.")).toBeInTheDocument();

    expect(getExportStatus).toHaveBeenCalledTimes(3);
  });

  it("shows polling failure error when async export returns failed", async () => {
    vi.mocked(createExport).mockResolvedValue({
      mode: "async",
      queued: {
        task_id: "task-failed",
        status: "queued",
        poll_url: "/api/v1/export/status/task-failed",
      },
    });

    vi.mocked(getExportStatus).mockResolvedValue({
      status: "failed",
      task_id: "task-failed",
      error: "Task failed in worker",
    });

    render(<ExportButton messageId="msg-1" rowCount={2} />);

    fireEvent.click(screen.getByRole("button", { name: /export as json/i }));

    await waitFor(() => {
      expect(screen.getByText(/JSON export: Task failed in worker/i)).toBeInTheDocument();
    });
  });

  it("shows timeout error when async polling exceeds max attempts", async () => {
    vi.useFakeTimers();

    vi.mocked(createExport).mockResolvedValue({
      mode: "async",
      queued: {
        task_id: "task-timeout",
        status: "queued",
        poll_url: "/api/v1/export/status/task-timeout",
      },
    });

    vi.mocked(getExportStatus).mockResolvedValue({
      status: "queued",
      task_id: "task-timeout",
    });

    render(<ExportButton messageId="msg-1" rowCount={2} />);

    fireEvent.click(screen.getByRole("button", { name: /export as netcdf/i }));

    await act(async () => {
      await Promise.resolve();
    });

    expect(getExportStatus).toHaveBeenCalledTimes(1);

    for (let index = 0; index < 41; index += 1) {
      await act(async () => {
        vi.advanceTimersByTime(3000);
        await Promise.resolve();
      });
    }

    expect(
      screen.getByText(/NetCDF export: Export is taking longer than expected\. Please try again\./i),
    ).toBeInTheDocument();
  });
});

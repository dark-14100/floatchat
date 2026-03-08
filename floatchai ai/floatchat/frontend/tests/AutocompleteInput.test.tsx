import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AutocompleteInput from "@/components/chat/AutocompleteInput";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("AutocompleteInput", () => {
  const mockedApiFetch = vi.mocked(apiFetch);

  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockResolvedValue([] as never);
  });

  it("submits free text directly when below suggestion threshold", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    render(
      <AutocompleteInput
        onSubmit={onSubmit}
        isLoading={false}
      />,
    );

    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.type(input, "x");
    await user.keyboard("{Enter}");

    expect(onSubmit).toHaveBeenCalledWith("x", {
      bypassClarification: false,
      source: "free_text",
    });
  });

  it("uses history suggestion first and submits with bypass", async () => {
    const user = userEvent.setup();
    const onSubmit = vi.fn();

    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/chat/query-history")) {
        return [
          {
            nl_query: "show temperature in indian ocean",
            created_at: "2026-03-01T00:00:00Z",
          },
        ] as never;
      }
      return [] as never;
    });

    render(
      <AutocompleteInput
        onSubmit={onSubmit}
        isLoading={false}
        userId="user-1"
      />,
    );

    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.type(input, "temperature");

    await screen.findByRole("listbox");

    // First Enter selects highlighted suggestion (inserts only)
    await user.keyboard("{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();

    // Submit selected suggestion via send button
    await user.click(screen.getByRole("button", { name: /send message/i }));

    await waitFor(() => {
      expect(onSubmit).toHaveBeenCalledTimes(1);
    });

    expect(onSubmit.mock.calls[0][0]).toBe("show temperature in indian ocean");
    expect(onSubmit.mock.calls[0][1]).toEqual({
      bypassClarification: true,
      source: "history",
    });
  });

  it("dismisses suggestion list on Escape", async () => {
    const user = userEvent.setup();

    render(
      <AutocompleteInput
        onSubmit={vi.fn()}
        isLoading={false}
      />,
    );

    const input = screen.getByRole("textbox");
    await user.click(input);
    await user.type(input, "te");

    await screen.findByRole("listbox");
    await user.keyboard("{Escape}");

    await waitFor(() => {
      expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    });
  });
});

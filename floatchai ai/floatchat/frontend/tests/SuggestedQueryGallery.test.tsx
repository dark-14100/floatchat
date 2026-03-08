import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import SuggestedQueryGallery from "@/components/chat/SuggestedQueryGallery";
import { apiFetch } from "@/lib/api";

vi.mock("@/lib/api", () => ({
  apiFetch: vi.fn(),
}));

describe("SuggestedQueryGallery", () => {
  const mockedApiFetch = vi.mocked(apiFetch);

  beforeEach(() => {
    mockedApiFetch.mockReset();
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/search/datasets/summaries")) {
        return {
          results: [],
          count: 0,
        } as never;
      }

      if (path.startsWith("/chat/query-history")) {
        return [] as never;
      }

      return [] as never;
    });
  });

  it("renders nothing when not visible", () => {
    mockedApiFetch.mockImplementation(
      () => new Promise(() => undefined) as never,
    );

    const { container } = render(
      <SuggestedQueryGallery
        visible={false}
        onQuerySelect={vi.fn()}
      />,
    );

    expect(container.innerHTML).toBe("");
  });

  it("selects a template query on card click", async () => {
    const user = userEvent.setup();
    const onQuerySelect = vi.fn();

    render(
      <SuggestedQueryGallery
        visible
        onQuerySelect={onQuerySelect}
      />,
    );

    const card = await screen.findByRole("button", {
      name: /surface temperature anomalies - north atlantic/i,
    });
    await user.click(card);

    expect(onQuerySelect).toHaveBeenCalledWith(
      "Show surface temperature anomalies in the North Atlantic this year.",
    );
  });

  it("shows For You tab when user has at least 5 history entries", async () => {
    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/chat/query-history")) {
        return [
          { nl_query: "show temperature in indian ocean", created_at: "2026-03-01T00:00:00Z" },
          { nl_query: "show salinity in indian ocean", created_at: "2026-03-02T00:00:00Z" },
          { nl_query: "show temperature in arabian sea", created_at: "2026-03-03T00:00:00Z" },
          { nl_query: "show oxygen in indian ocean", created_at: "2026-03-04T00:00:00Z" },
          { nl_query: "show nitrate in indian ocean", created_at: "2026-03-05T00:00:00Z" },
        ] as never;
      }
      return {
        results: [],
        count: 0,
      } as never;
    });

    render(
      <SuggestedQueryGallery
        visible
        userId="user-123"
        onQuerySelect={vi.fn()}
      />,
    );

    await screen.findByRole("button", { name: "For You" });
  });

  it("shows Recently Added badge when recent dataset variables match card variables", async () => {
    const recentIso = new Date().toISOString();

    mockedApiFetch.mockImplementation(async (path: string) => {
      if (path.startsWith("/search/datasets/summaries")) {
        return {
          results: [
            {
              variable_list: ["temperature", "salinity"],
              date_range_end: recentIso,
            },
          ],
          count: 1,
        } as never;
      }
      return [] as never;
    });

    render(
      <SuggestedQueryGallery
        visible
        onQuerySelect={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Recently Added").length).toBeGreaterThan(0);
    });
  });
});

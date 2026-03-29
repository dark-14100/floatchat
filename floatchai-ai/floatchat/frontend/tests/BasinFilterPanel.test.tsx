import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import BasinFilterPanel, { ALL_BASIN_NAMES } from "@/components/map/BasinFilterPanel";

describe("BasinFilterPanel", () => {
  it("renders both basin groups and all configured basin names", () => {
    render(
      <BasinFilterPanel
        activeBasin={null}
        onBasinSelect={vi.fn()}
        onShowAll={vi.fn()}
      />,
    );

    expect(screen.getByText("Major Basins")).toBeInTheDocument();
    expect(screen.getByText("Sub-regions")).toBeInTheDocument();

    for (const basinName of ALL_BASIN_NAMES) {
      expect(screen.getByText(basinName)).toBeInTheDocument();
    }

    expect(screen.getByRole("button", { name: /show all basins/i })).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(ALL_BASIN_NAMES.length + 1);
  });
});

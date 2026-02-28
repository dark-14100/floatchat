/**
 * ResultTable component tests.
 *
 * - Correct row count display
 * - Truncated badge
 * - Column sort
 * - Show more toggle
 * - Returns null for empty data
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect } from "vitest";
import ResultTable from "@/components/chat/ResultTable";

const COLUMNS = ["float_id", "temperature", "depth", "timestamp"];

function makeRows(count: number) {
  return Array.from({ length: count }, (_, i) => ({
    float_id: `F${i + 1}`,
    temperature: 15.1234 + i * 0.1,
    depth: (i + 1) * 100,
    timestamp: "2026-01-15T10:00:00Z",
  }));
}

describe("ResultTable", () => {
  it("renders the correct row count", () => {
    render(
      <ResultTable
        columns={COLUMNS}
        rows={makeRows(5)}
        rowCount={5}
        truncated={false}
      />,
    );
    expect(screen.getByText("5 rows")).toBeInTheDocument();
  });

  it("displays singular 'row' for rowCount=1", () => {
    render(
      <ResultTable
        columns={COLUMNS}
        rows={makeRows(1)}
        rowCount={1}
        truncated={false}
      />,
    );
    expect(screen.getByText("1 row")).toBeInTheDocument();
  });

  it("shows truncated badge when truncated is true", () => {
    render(
      <ResultTable
        columns={COLUMNS}
        rows={makeRows(5)}
        rowCount={10000}
        truncated={true}
      />,
    );
    expect(screen.getByText("Truncated")).toBeInTheDocument();
    expect(screen.getByTitle("Results were limited to 10,000 rows")).toBeInTheDocument();
  });

  it("does not show truncated badge when truncated is false", () => {
    render(
      <ResultTable
        columns={COLUMNS}
        rows={makeRows(5)}
        rowCount={5}
        truncated={false}
      />,
    );
    expect(screen.queryByText("Truncated")).not.toBeInTheDocument();
  });

  it("renders column headers", () => {
    render(
      <ResultTable
        columns={COLUMNS}
        rows={makeRows(3)}
        rowCount={3}
        truncated={false}
      />,
    );
    COLUMNS.forEach((col) => {
      expect(screen.getByText(col)).toBeInTheDocument();
    });
  });

  it("sorts rows when a header is clicked", async () => {
    const user = userEvent.setup();
    const rows = [
      { float_id: "B", temperature: 20.0, depth: 200, timestamp: "2026-01-15T10:00:00Z" },
      { float_id: "A", temperature: 10.0, depth: 100, timestamp: "2026-01-15T10:00:00Z" },
      { float_id: "C", temperature: 30.0, depth: 300, timestamp: "2026-01-15T10:00:00Z" },
    ];

    render(
      <ResultTable
        columns={COLUMNS}
        rows={rows}
        rowCount={3}
        truncated={false}
      />,
    );

    // Click "float_id" header to sort ascending
    await user.click(screen.getByText("float_id"));

    const cells = screen.getAllByRole("cell");
    // First column cells should be A, B, C after ascending sort
    const firstColValues = cells
      .filter((_, i) => i % COLUMNS.length === 0)
      .map((c) => c.textContent);
    expect(firstColValues).toEqual(["A", "B", "C"]);
  });

  it("shows 'Show all' button when rows exceed 100", () => {
    render(
      <ResultTable
        columns={COLUMNS}
        rows={makeRows(150)}
        rowCount={150}
        truncated={false}
      />,
    );
    expect(screen.getByText(/Show all 150 rows/)).toBeInTheDocument();
  });

  it("returns null when rows array is empty", () => {
    const { container } = render(
      <ResultTable
        columns={COLUMNS}
        rows={[]}
        rowCount={0}
        truncated={false}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("returns null when columns array is empty", () => {
    const { container } = render(
      <ResultTable
        columns={[]}
        rows={makeRows(5)}
        rowCount={5}
        truncated={false}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("formats numbers with toFixed(4)", () => {
    render(
      <ResultTable
        columns={["value"]}
        rows={[{ value: 3.14159265 }]}
        rowCount={1}
        truncated={false}
      />,
    );
    expect(screen.getByText("3.1416")).toBeInTheDocument();
  });

  it("displays null values as em dash", () => {
    render(
      <ResultTable
        columns={["value"]}
        rows={[{ value: null }]}
        rowCount={1}
        truncated={false}
      />,
    );
    expect(screen.getByText("—")).toBeInTheDocument();
  });
});

"use client";

/**
 * ResultTable — Inline data table rendered inside ChatMessage.
 *
 * Features:
 * - HTML <table> with Tailwind styling
 * - Column sort (click headers)
 * - Show first 100 rows + "Show more" toggle
 * - Horizontal scroll via overflow-x-auto
 * - toFixed(4) for numbers
 * - Intl.DateTimeFormat for timestamps
 * - Amber highlight for is_outlier rows
 * - "Truncated" badge when truncated = true
 */

import { useCallback, useMemo, useState } from "react";
import { ArrowUpDown, ArrowUp, ArrowDown, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

// ── Types ──────────────────────────────────────────────────────────────────

interface ResultTableProps {
  columns: string[];
  rows: Record<string, string | number | boolean | null>[];
  rowCount: number;
  truncated: boolean;
}

type SortDir = "asc" | "desc" | null;

interface SortState {
  column: string | null;
  direction: SortDir;
}

// ── Constants ──────────────────────────────────────────────────────────────

const INITIAL_ROWS = 100;
const TIMESTAMP_COLS = ["timestamp", "date", "time", "created_at", "updated_at", "observation_date", "juld"];

// ── Helpers ────────────────────────────────────────────────────────────────

const dateFormatter = new Intl.DateTimeFormat("en-US", {
  year: "numeric",
  month: "short",
  day: "numeric",
  hour: "2-digit",
  minute: "2-digit",
  timeZoneName: "short",
});

function isTimestampCol(col: string): boolean {
  const lower = col.toLowerCase();
  return TIMESTAMP_COLS.some((tc) => lower.includes(tc));
}

function formatCell(value: string | number | boolean | null, col: string): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "true" : "false";

  if (typeof value === "number") {
    if (Number.isInteger(value)) return value.toLocaleString();
    return value.toFixed(4);
  }

  // String — check if it's a timestamp column
  if (isTimestampCol(col)) {
    const d = new Date(value);
    if (!isNaN(d.getTime())) return dateFormatter.format(d);
  }

  return String(value);
}

function compareValues(
  a: string | number | boolean | null,
  b: string | number | boolean | null,
): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b));
}

// ── Component ──────────────────────────────────────────────────────────────

export default function ResultTable({
  columns,
  rows,
  rowCount,
  truncated,
}: ResultTableProps) {
  const [sort, setSort] = useState<SortState>({ column: null, direction: null });
  const [showAll, setShowAll] = useState(false);

  const handleSort = useCallback((col: string) => {
    setSort((prev) => {
      if (prev.column !== col) return { column: col, direction: "asc" };
      if (prev.direction === "asc") return { column: col, direction: "desc" };
      return { column: null, direction: null };
    });
  }, []);

  const sortedRows = useMemo(() => {
    if (!sort.column || !sort.direction) return rows;
    const col = sort.column;
    const dir = sort.direction === "asc" ? 1 : -1;
    return [...rows].sort((a, b) => dir * compareValues(a[col], b[col]));
  }, [rows, sort]);

  const displayRows = showAll ? sortedRows : sortedRows.slice(0, INITIAL_ROWS);
  const hasMore = sortedRows.length > INITIAL_ROWS;

  if (columns.length === 0 || rows.length === 0) return null;

  return (
    <div className="my-3 space-y-2">
      {/* Header with row count + truncated badge */}
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span>
          {rowCount.toLocaleString()} row{rowCount !== 1 ? "s" : ""}
        </span>
        {truncated && (
          <span
            className="inline-flex items-center gap-1 rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-400"
            title="Results were limited to 10,000 rows"
          >
            <AlertTriangle className="h-3 w-3" />
            Truncated
          </span>
        )}
      </div>

      {/* Scrollable table */}
      <div className="overflow-x-auto rounded-md border border-border">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-border bg-muted/50">
              {columns.map((col) => (
                <th
                  key={col}
                  className="cursor-pointer whitespace-nowrap px-3 py-2 font-medium text-muted-foreground hover:text-foreground"
                  onClick={() => handleSort(col)}
                >
                  <span className="inline-flex items-center gap-1">
                    {col}
                    {sort.column === col ? (
                      sort.direction === "asc" ? (
                        <ArrowUp className="h-3 w-3" />
                      ) : (
                        <ArrowDown className="h-3 w-3" />
                      )
                    ) : (
                      <ArrowUpDown className="h-3 w-3 opacity-30" />
                    )}
                  </span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((row, idx) => {
              const isOutlier =
                "is_outlier" in row && (row.is_outlier === true || row.is_outlier === 1);
              return (
                <tr
                  key={idx}
                  className={`border-b border-border last:border-0 ${
                    isOutlier
                      ? "bg-amber-500/10 text-amber-200"
                      : "hover:bg-muted/30"
                  }`}
                >
                  {columns.map((col) => (
                    <td
                      key={col}
                      className="whitespace-nowrap px-3 py-1.5 tabular-nums"
                    >
                      {formatCell(row[col], col)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Show more / Show less */}
      {hasMore && (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => setShowAll((prev) => !prev)}
          className="text-xs"
        >
          {showAll
            ? "Show less"
            : `Show all ${sortedRows.length.toLocaleString()} rows`}
        </Button>
      )}
    </div>
  );
}

"use client";

import { Circle, Filter, Pentagon, RotateCcw, ZoomIn, ZoomOut } from "lucide-react";

export type FloatTypeFilter = "all" | "bgc" | "core";

interface MapToolbarProps {
  onZoomIn: () => void;
  onZoomOut: () => void;
  onDrawCircleToggle: () => void;
  onDrawPolygonToggle: () => void;
  onResetView: () => void;
  floatTypeFilter: FloatTypeFilter;
  onFloatTypeFilterChange: (filter: FloatTypeFilter) => void;
}

export default function MapToolbar({
  onZoomIn,
  onZoomOut,
  onDrawCircleToggle,
  onDrawPolygonToggle,
  onResetView,
  floatTypeFilter,
  onFloatTypeFilterChange,
}: MapToolbarProps) {
  const baseBtn =
    "inline-flex h-10 w-10 items-center justify-center rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] text-[var(--color-text-primary)] shadow-sm transition-colors hover:bg-[var(--color-bg-elevated)]";

  return (
    <div className="absolute right-4 top-4 z-[1000] flex flex-col gap-2">
      <button className={baseBtn} onClick={onZoomIn} aria-label="Zoom in" title="Zoom in">
        <ZoomIn className="h-4 w-4" />
      </button>
      <button className={baseBtn} onClick={onZoomOut} aria-label="Zoom out" title="Zoom out">
        <ZoomOut className="h-4 w-4" />
      </button>
      <button className={baseBtn} onClick={onDrawCircleToggle} aria-label="Draw circle" title="Draw circle">
        <Circle className="h-4 w-4" />
      </button>
      <button className={baseBtn} onClick={onDrawPolygonToggle} aria-label="Draw polygon" title="Draw polygon">
        <Pentagon className="h-4 w-4" />
      </button>
      <button className={baseBtn} onClick={onResetView} aria-label="Reset view" title="Reset view">
        <RotateCcw className="h-4 w-4" />
      </button>

      <div className="mt-1 rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-surface)] p-2 shadow-sm">
        <div className="mb-1 flex items-center gap-1 text-xs text-[var(--color-text-secondary)]">
          <Filter className="h-3.5 w-3.5" />
          <span>Float type</span>
        </div>
        <div className="flex gap-1">
          {([
            ["all", "All"],
            ["bgc", "BGC"],
            ["core", "Core"],
          ] as const).map(([value, label]) => {
            const active = floatTypeFilter === value;
            return (
              <button
                key={value}
                onClick={() => onFloatTypeFilterChange(value)}
                className={[
                  "rounded px-2 py-1 text-xs font-medium transition-colors",
                  active
                    ? "bg-[var(--color-ocean-primary)] text-[var(--color-text-inverse)]"
                    : "bg-[var(--color-bg-subtle)] text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]",
                ].join(" ")}
                aria-label={`Show ${label} floats`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

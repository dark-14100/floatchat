"use client";

import { useMemo, useState } from "react";

import { getBasinFloats, type BasinFloat } from "@/lib/mapQueries";

const MAJOR_BASINS = [
  "Indian Ocean",
  "Pacific Ocean (North)",
  "Pacific Ocean (South)",
  "Atlantic Ocean (North)",
  "Atlantic Ocean (South)",
  "Southern Ocean",
  "Arctic Ocean",
] as const;

const SUB_REGIONS = [
  "Arabian Sea",
  "Bay of Bengal",
  "Caribbean Sea",
  "Mediterranean Sea",
  "Red Sea",
  "Persian Gulf",
  "Gulf of Mexico",
  "Laccadive Sea",
] as const;

export const ALL_BASIN_NAMES: string[] = [...MAJOR_BASINS, ...SUB_REGIONS];

interface BasinFilterPanelProps {
  activeBasin: string | null;
  onBasinSelect: (basinName: string, floats: BasinFloat[]) => void;
  onShowAll: () => void;
}

export default function BasinFilterPanel({
  activeBasin,
  onBasinSelect,
  onShowAll,
}: BasinFilterPanelProps) {
  const [loadingBasin, setLoadingBasin] = useState<string | null>(null);
  const [countsByBasin, setCountsByBasin] = useState<Record<string, number>>({});

  const basinGroups = useMemo(
    () => [
      { label: "Major Basins", items: MAJOR_BASINS },
      { label: "Sub-regions", items: SUB_REGIONS },
    ],
    [],
  );

  const handleSelect = async (basinName: string) => {
    setLoadingBasin(basinName);
    try {
      const floats = await getBasinFloats(basinName);
      setCountsByBasin((prev) => ({ ...prev, [basinName]: floats.length }));
      onBasinSelect(basinName, floats);
    } catch {
      setCountsByBasin((prev) => ({ ...prev, [basinName]: 0 }));
      onBasinSelect(basinName, []);
    } finally {
      setLoadingBasin(null);
    }
  };

  return (
    <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">Basin filter</h2>
        <button
          onClick={onShowAll}
          className="text-xs text-[var(--color-ocean-primary)] hover:underline"
        >
          Show all basins
        </button>
      </div>

      <div className="max-h-[260px] space-y-3 overflow-y-auto pr-1">
        {basinGroups.map((group) => (
          <div key={group.label}>
            <div className="mb-1 text-[10px] font-medium uppercase tracking-wide text-[var(--color-text-muted)]">
              {group.label}
            </div>
            <div className="space-y-1">
              {group.items.map((name) => {
                const isActive = activeBasin === name;
                const count = countsByBasin[name];
                const loading = loadingBasin === name;

                return (
                  <button
                    key={name}
                    onClick={() => handleSelect(name)}
                    className={[
                      "flex w-full items-center justify-between rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                      isActive
                        ? "border border-[var(--color-ocean-primary)] bg-[var(--color-ocean-lighter)] text-[var(--color-ocean-deep)]"
                        : "border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] text-[var(--color-text-secondary)] hover:bg-[var(--color-bg-subtle)]",
                    ].join(" ")}
                  >
                    <span>{name}</span>
                    <span className="text-[10px]">
                      {loading ? "…" : count !== undefined ? count : "-"}
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

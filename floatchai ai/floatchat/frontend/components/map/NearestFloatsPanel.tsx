"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";

import type { NearestFloat } from "@/lib/mapQueries";

interface NearestFloatsPanelProps {
  point: { lat: number; lon: number };
  floats: NearestFloat[];
  loading?: boolean;
  onFloatSelect: (platformNumber: string) => void;
  onClear: () => void;
}

export default function NearestFloatsPanel({
  point,
  floats,
  loading = false,
  onFloatSelect,
  onClear,
}: NearestFloatsPanelProps) {
  const router = useRouter();

  const queryString = useMemo(() => {
    const wmOs = floats.slice(0, 10).map((row) => row.platform_number).join(", ");
    return `show recent profiles from floats ${wmOs}`;
  }, [floats]);

  return (
    <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">
        Nearest floats to {point.lat.toFixed(3)}, {point.lon.toFixed(3)}
      </h2>

      <div className="mt-3 max-h-[280px] space-y-2 overflow-y-auto pr-1">
        {loading && (
          <div className="rounded-md bg-[var(--color-bg-elevated)] p-2 text-xs text-[var(--color-text-secondary)]">
            Finding nearest floats…
          </div>
        )}

        {!loading && floats.length === 0 && (
          <div className="rounded-md bg-[var(--color-bg-elevated)] p-2 text-xs text-[var(--color-text-secondary)]">
            No nearby floats found.
          </div>
        )}

        {floats.map((row) => (
          <button
            key={`${row.platform_number}-${row.distance_km}`}
            onClick={() => onFloatSelect(row.platform_number)}
            className="w-full rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-2 text-left transition-colors hover:bg-[var(--color-bg-subtle)]"
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-[var(--color-text-primary)]">
                {row.platform_number}
              </span>
              <span className="rounded-full bg-[var(--color-ocean-lighter)] px-2 py-0.5 text-[10px] font-medium text-[var(--color-ocean-deep)]">
                {row.float_type ?? "unknown"}
              </span>
            </div>
            <div className="mt-1 text-xs text-[var(--color-text-secondary)]">
              {row.distance_km.toFixed(1)} km • Last seen {row.last_seen ? new Date(row.last_seen).toLocaleDateString() : "unknown"}
            </div>
          </button>
        ))}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => router.push(`/chat?prefill=${encodeURIComponent(queryString)}`)}
          disabled={floats.length === 0 || loading}
          className="flex-1 rounded-md bg-[var(--color-ocean-primary)] px-3 py-2 text-xs font-medium text-[var(--color-text-inverse)] disabled:opacity-60"
        >
          Query these floats in chat
        </button>
        <button
          onClick={onClear}
          className="rounded-md border border-[var(--color-border-default)] px-3 py-2 text-xs text-[var(--color-text-secondary)]"
        >
          Clear
        </button>
      </div>
    </div>
  );
}

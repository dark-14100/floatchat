"use client";

import { useEffect, useMemo, useState } from "react";
import { point } from "@turf/helpers";
import booleanValid from "@turf/boolean-valid";
import { useRouter } from "next/navigation";

import { postRadiusQuery, type RadiusQueryResult } from "@/lib/mapQueries";

interface RadiusQueryPanelProps {
  center: { lat: number; lon: number };
  initialRadiusKm: number;
  onRadiusChange: (km: number) => void;
  onClear: () => void;
}

export default function RadiusQueryPanel({
  center,
  initialRadiusKm,
  onRadiusChange,
  onClear,
}: RadiusQueryPanelProps) {
  const router = useRouter();

  const [radiusKm, setRadiusKm] = useState<number>(Math.max(50, Math.min(2000, initialRadiusKm)));
  const [loading, setLoading] = useState<boolean>(false);
  const [result, setResult] = useState<RadiusQueryResult | null>(null);

  useEffect(() => {
    setRadiusKm(Math.max(50, Math.min(2000, initialRadiusKm)));
  }, [initialRadiusKm]);

  useEffect(() => {
    const centerPoint = point([center.lon, center.lat]);
    if (!booleanValid(centerPoint)) {
      setResult(null);
      return;
    }

    const timer = setTimeout(() => {
      setLoading(true);
      postRadiusQuery(center.lat, center.lon, radiusKm)
        .then(setResult)
        .catch(() => setResult(null))
        .finally(() => setLoading(false));
    }, 300);

    return () => clearTimeout(timer);
  }, [center.lat, center.lon, radiusKm]);

  const queryString = useMemo(
    () => `show profiles within ${Math.round(radiusKm)}km of latitude ${center.lat.toFixed(4)}, longitude ${center.lon.toFixed(4)}`,
    [radiusKm, center.lat, center.lon],
  );

  return (
    <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <h2 className="text-sm font-semibold text-[var(--color-text-primary)]">Radius query</h2>
      <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
        Center: {center.lat.toFixed(4)}, {center.lon.toFixed(4)}
      </p>

      <div className="mt-3">
        <label className="mb-1 block text-xs text-[var(--color-text-secondary)]">
          Radius: {radiusKm} km
        </label>
        <input
          type="range"
          min={50}
          max={2000}
          step={50}
          value={radiusKm}
          onChange={(e) => {
            const next = Number(e.target.value);
            setRadiusKm(next);
            onRadiusChange(next);
          }}
          className="w-full"
        />
      </div>

      <div className="mt-3 rounded-md bg-[var(--color-bg-elevated)] p-2 text-xs text-[var(--color-text-secondary)]">
        {loading && <span>Running radius query…</span>}
        {!loading && result && (
          <span>
            Profiles: <strong>{result.profile_count}</strong> • Floats: <strong>{result.float_count}</strong>
          </span>
        )}
        {!loading && !result && <span>No results available.</span>}
      </div>

      <div className="mt-3 flex gap-2">
        <button
          onClick={() => router.push(`/chat?prefill=${encodeURIComponent(queryString)}`)}
          className="flex-1 rounded-md bg-[var(--color-ocean-primary)] px-3 py-2 text-xs font-medium text-[var(--color-text-inverse)]"
        >
          Query in Chat
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

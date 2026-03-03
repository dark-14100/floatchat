"use client";

import { useMemo, useState } from "react";
import { Search } from "lucide-react";

import geographyLookup from "@/lib/geographyLookup.json";
import { ALL_BASIN_NAMES } from "@/components/map/BasinFilterPanel";

interface SearchBarProps {
  onLocationResolved: (lat: number, lon: number, label: string) => void;
  onBasinResolved: (basinName: string) => void;
}

interface LookupEntry {
  lat_min: number;
  lat_max: number;
  lon_min: number;
  lon_max: number;
}

function normalizeLongitude(lon: number): number {
  let value = lon;
  while (value > 180) value -= 360;
  while (value < -180) value += 360;
  return value;
}

function centerFromBounds(entry: LookupEntry): { lat: number; lon: number } {
  const lat = (entry.lat_min + entry.lat_max) / 2;

  let lon: number;
  if (entry.lon_min <= entry.lon_max) {
    lon = (entry.lon_min + entry.lon_max) / 2;
  } else {
    const wrappedMax = entry.lon_max + 360;
    lon = (entry.lon_min + wrappedMax) / 2;
  }

  return { lat, lon: normalizeLongitude(lon) };
}

function parseDecimalPair(input: string): { lat: number; lon: number } | null {
  const regex = /^\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*$/;
  const match = input.match(regex);
  if (!match) return null;

  const lat = Number(match[1]);
  const lon = Number(match[2]);
  if (Number.isNaN(lat) || Number.isNaN(lon)) return null;
  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;

  return { lat, lon };
}

function parseDms(input: string): { lat: number; lon: number } | null {
  const regex = /(\d{1,2})[°\s]+(\d{1,2})?['\s]*([NS])\s*,?\s*(\d{1,3})[°\s]+(\d{1,2})?['\s]*([EW])/i;
  const match = input.match(regex);
  if (!match) return null;

  const latDeg = Number(match[1]);
  const latMin = Number(match[2] ?? 0);
  const latHem = match[3].toUpperCase();

  const lonDeg = Number(match[4]);
  const lonMin = Number(match[5] ?? 0);
  const lonHem = match[6].toUpperCase();

  let lat = latDeg + latMin / 60;
  let lon = lonDeg + lonMin / 60;

  if (latHem === "S") lat *= -1;
  if (lonHem === "W") lon *= -1;

  if (lat < -90 || lat > 90 || lon < -180 || lon > 180) return null;

  return { lat, lon };
}

export default function SearchBar({ onLocationResolved, onBasinResolved }: SearchBarProps) {
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);

  const lookupMap = useMemo(() => {
    const entries = Object.entries(geographyLookup) as Array<[string, unknown]>;
    const filtered = entries.filter(([key, entry]) => {
      if (key.startsWith("_")) return false;
      if (typeof entry !== "object" || entry === null) return false;
      const candidate = entry as Partial<LookupEntry>;
      return (
        typeof candidate.lat_min === "number" &&
        typeof candidate.lat_max === "number" &&
        typeof candidate.lon_min === "number" &&
        typeof candidate.lon_max === "number"
      );
    });

    return new Map<string, LookupEntry>(
      filtered.map(([key, entry]) => [key.toLowerCase(), entry as LookupEntry]),
    );
  }, []);

  const basinNameMap = useMemo(
    () => new Map(ALL_BASIN_NAMES.map((name) => [name.toLowerCase(), name])),
    [],
  );

  const resolveInput = () => {
    const trimmed = value.trim();
    if (!trimmed) {
      setError(null);
      return;
    }

    setError(null);

    const decimal = parseDecimalPair(trimmed);
    if (decimal) {
      onLocationResolved(decimal.lat, decimal.lon, trimmed);
      return;
    }

    const dms = parseDms(trimmed);
    if (dms) {
      onLocationResolved(dms.lat, dms.lon, trimmed);
      return;
    }

    const basinMatch = basinNameMap.get(trimmed.toLowerCase());
    if (basinMatch) {
      onBasinResolved(basinMatch);
      return;
    }

    const lookupEntry = lookupMap.get(trimmed.toLowerCase());
    if (lookupEntry) {
      const center = centerFromBounds(lookupEntry);
      onLocationResolved(center.lat, center.lon, trimmed);
      return;
    }

    setError("Location not found");
  };

  return (
    <div className="rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
      <label className="mb-1 block text-xs font-medium text-[var(--color-text-primary)]">Search location</label>
      <div className="flex items-center gap-2 rounded-md border border-[var(--color-border-default)] bg-[var(--color-bg-elevated)] px-2 py-1.5">
        <Search className="h-4 w-4 text-[var(--color-text-muted)]" />
        <input
          value={value}
          onChange={(event) => setValue(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              resolveInput();
            }
          }}
          placeholder="12.5, 80.2 • Arabian Sea • Chennai"
          className="w-full bg-transparent text-xs text-[var(--color-text-primary)] outline-none"
        />
        <button
          onClick={resolveInput}
          className="rounded bg-[var(--color-ocean-primary)] px-2 py-1 text-[10px] font-medium text-[var(--color-text-inverse)]"
        >
          Go
        </button>
      </div>
      {error && <p className="mt-1 text-xs text-[var(--color-coral)]">{error}</p>}
    </div>
  );
}

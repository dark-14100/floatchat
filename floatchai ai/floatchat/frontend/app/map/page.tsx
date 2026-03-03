"use client";

import dynamic from "next/dynamic";
import { useCallback, useMemo, useRef, useState } from "react";

import {
  getBasinFloats,
  getNearestFloats,
  type ActiveFloat,
  type BasinFloat,
  type NearestFloat,
} from "@/lib/mapQueries";
import type { FloatTypeFilter } from "@/components/map/MapToolbar";
import type { ExplorationMapHandle } from "@/components/map/ExplorationMap";

const ExplorationMap = dynamic(
  () => import("@/components/map/ExplorationMap"),
  { ssr: false },
);

const MapToolbar = dynamic(
  () => import("@/components/map/MapToolbar"),
  { ssr: false },
);

const NearestFloatsPanel = dynamic(
  () => import("@/components/map/NearestFloatsPanel"),
  { ssr: false },
);

const RadiusQueryPanel = dynamic(
  () => import("@/components/map/RadiusQueryPanel"),
  { ssr: false },
);

const FloatDetailPanel = dynamic(
  () => import("@/components/map/FloatDetailPanel"),
  { ssr: false },
);

const BasinFilterPanel = dynamic(
  () => import("@/components/map/BasinFilterPanel"),
  { ssr: false },
);

const SearchBar = dynamic(
  () => import("@/components/map/SearchBar"),
  { ssr: false },
);

type ActivePanel = "none" | "nearest" | "radius" | "detail";

export default function MapPage() {
  const mapRef = useRef<ExplorationMapHandle | null>(null);

  const [activePanel, setActivePanel] = useState<ActivePanel>("none");
  const [selectedPoint, setSelectedPoint] = useState<{ lat: number; lon: number } | null>(null);
  const [selectedFloat, setSelectedFloat] = useState<string | null>(null);
  const [drawnRadius, setDrawnRadius] = useState<{ center: { lat: number; lon: number }; radius_km: number } | null>(null);
  const [activeBasin, setActiveBasin] = useState<string | null>(null);
  const [basinFloats, setBasinFloats] = useState<BasinFloat[] | null>(null);
  const [drawCircleMode, setDrawCircleMode] = useState<boolean>(false);

  const [activeFloats, setActiveFloats] = useState<ActiveFloat[]>([]);
  const [floatTypeFilter, setFloatTypeFilter] = useState<FloatTypeFilter>("all");
  const [nearestFloats, setNearestFloats] = useState<NearestFloat[]>([]);
  const [nearestLoading, setNearestLoading] = useState<boolean>(false);

  const filteredFloatsCount = useMemo(() => {
    const base = activeBasin && basinFloats ? basinFloats : activeFloats;
    if (floatTypeFilter === "all") return base.length;
    return base.filter((f) => (f.float_type ?? "").toLowerCase() === floatTypeFilter).length;
  }, [activeFloats, basinFloats, activeBasin, floatTypeFilter]);

  const handleMapClick = useCallback(async (lat: number, lon: number) => {
    setSelectedPoint({ lat, lon });
    setSelectedFloat(null);
    setActivePanel("nearest");

    setNearestLoading(true);
    try {
      const rows = await getNearestFloats(lat, lon);
      setNearestFloats(rows);
    } catch {
      setNearestFloats([]);
    } finally {
      setNearestLoading(false);
    }
  }, []);

  const handleFloatClick = useCallback((platformNumber: string) => {
    setSelectedFloat(platformNumber);
    setActivePanel("detail");
  }, []);

  const clearNearest = useCallback(() => {
    setSelectedPoint(null);
    setNearestFloats([]);
    setActivePanel("none");
  }, []);

  const clearRadius = useCallback(() => {
    setDrawnRadius(null);
    setActivePanel("none");
  }, []);

  const handleLocationResolved = useCallback(
    (lat: number, lon: number) => {
      setActiveBasin(null);
      setBasinFloats(null);
      mapRef.current?.flyTo(lat, lon, 6);
      void handleMapClick(lat, lon);
    },
    [handleMapClick],
  );

  const handleBasinSelect = useCallback((basinName: string, floats: BasinFloat[]) => {
    setActiveBasin(basinName);
    setBasinFloats(floats);
    setActivePanel("none");

    const first = floats.find((row) => row.latitude !== null && row.longitude !== null);
    if (first && first.latitude !== null && first.longitude !== null) {
      mapRef.current?.flyTo(first.latitude, first.longitude, 5);
    }
  }, []);

  const handleBasinResolvedFromSearch = useCallback(async (basinName: string) => {
    try {
      const rows = await getBasinFloats(basinName);
      handleBasinSelect(basinName, rows);
    } catch {
      handleBasinSelect(basinName, []);
    }
  }, [handleBasinSelect]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[var(--color-bg-base)] text-[var(--color-text-primary)]">
      <aside className="relative z-[2] flex h-full w-[240px] flex-col border-r border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-4">
        <div className="mb-4">
          <h1 className="text-lg font-semibold">Geospatial Map</h1>
          <p className="mt-1 text-xs text-[var(--color-text-secondary)]">
            Active floats: {activeFloats.length}
          </p>
          <p className="text-xs text-[var(--color-text-secondary)]">
            Visible ({floatTypeFilter.toUpperCase()}): {filteredFloatsCount}
          </p>
        </div>

        <div className="mb-3">
          <SearchBar
            onLocationResolved={handleLocationResolved}
            onBasinResolved={handleBasinResolvedFromSearch}
          />
        </div>

        <div className="mb-3">
          <BasinFilterPanel
            activeBasin={activeBasin}
            onBasinSelect={handleBasinSelect}
            onShowAll={() => {
              setActiveBasin(null);
              setBasinFloats(null);
            }}
          />
        </div>

        <div className="space-y-3 overflow-y-auto text-xs text-[var(--color-text-secondary)]">
          {activePanel === "nearest" && selectedPoint && (
            <NearestFloatsPanel
              point={selectedPoint}
              floats={nearestFloats}
              loading={nearestLoading}
              onFloatSelect={(platformNumber) => {
                setSelectedFloat(platformNumber);
                setActivePanel("detail");
              }}
              onClear={clearNearest}
            />
          )}

          {activePanel === "detail" && selectedFloat && (
            <FloatDetailPanel
              platformNumber={selectedFloat}
              onClose={() => {
                setSelectedFloat(null);
                setActivePanel("none");
              }}
            />
          )}

          {activePanel === "radius" && drawnRadius && (
            <RadiusQueryPanel
              center={drawnRadius.center}
              initialRadiusKm={drawnRadius.radius_km}
              onRadiusChange={(nextRadiusKm) => {
                setDrawnRadius((prev) =>
                  prev
                    ? {
                        center: prev.center,
                        radius_km: nextRadiusKm,
                      }
                    : prev,
                );
              }}
              onClear={clearRadius}
            />
          )}

          {activePanel === "none" && (
            <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-3">
              Click the ocean for nearest floats, click a marker for details, or use Draw circle.
            </div>
          )}

          {activeBasin && (
            <div className="rounded-md border border-[var(--color-border-subtle)] bg-[var(--color-bg-elevated)] p-3">
              <div className="font-medium text-[var(--color-text-primary)]">Active Basin</div>
              <div className="mt-1">{activeBasin}</div>
            </div>
          )}
        </div>
      </aside>

      <section className="relative h-full flex-1">
        <ExplorationMap
          ref={mapRef}
          selectedFloat={selectedFloat}
          floatTypeFilter={floatTypeFilter}
          activeBasin={activeBasin}
          basinFloats={basinFloats}
          drawnRadius={drawnRadius}
          drawCircleMode={drawCircleMode}
          onMapClick={handleMapClick}
          onFloatClick={handleFloatClick}
          onCircleDrawn={(payload) => {
            setDrawnRadius(payload);
            setActivePanel("radius");
          }}
          onCircleModeHandled={() => setDrawCircleMode(false)}
          onFloatsLoaded={setActiveFloats}
        />

        <MapToolbar
          onZoomIn={() => mapRef.current?.zoomIn()}
          onZoomOut={() => mapRef.current?.zoomOut()}
          onDrawCircleToggle={() => setDrawCircleMode(true)}
          onDrawPolygonToggle={() => setActiveBasin(null)}
          onResetView={() => mapRef.current?.resetView()}
          floatTypeFilter={floatTypeFilter}
          onFloatTypeFilterChange={setFloatTypeFilter}
        />
      </section>
    </div>
  );
}

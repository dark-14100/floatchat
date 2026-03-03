"use client";

import {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  CircleMarker,
  Circle,
  GeoJSON,
  MapContainer,
  TileLayer,
  Tooltip,
  useMapEvents,
} from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import L, { type LeafletMouseEvent, type Map as LeafletMap } from "leaflet";
import "leaflet-draw";

import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM } from "@/lib/colorscales";
import {
  getActiveFloats,
  getBasinPolygons,
  type ActiveFloat,
  type BasinFloat,
  type BasinPolygonFeature,
} from "@/lib/mapQueries";
import type { FloatTypeFilter } from "@/components/map/MapToolbar";

interface ExplorationMapProps {
  selectedFloat: string | null;
  floatTypeFilter: FloatTypeFilter;
  activeBasin: string | null;
  basinFloats: BasinFloat[] | null;
  drawnRadius: { center: { lat: number; lon: number }; radius_km: number } | null;
  drawCircleMode: boolean;
  onMapClick: (lat: number, lon: number) => void;
  onFloatClick: (platformNumber: string) => void;
  onCircleDrawn: (payload: { center: { lat: number; lon: number }; radius_km: number }) => void;
  onCircleModeHandled: () => void;
  onFloatsLoaded?: (floats: ActiveFloat[]) => void;
}

export interface ExplorationMapHandle {
  zoomIn: () => void;
  zoomOut: () => void;
  resetView: () => void;
  flyTo: (lat: number, lon: number, zoom?: number) => void;
}

function MapClickHandler({ onMapClick }: { onMapClick: (lat: number, lon: number) => void }) {
  useMapEvents({
    click: (event: LeafletMouseEvent) => {
      onMapClick(event.latlng.lat, event.latlng.lng);
    },
  });
  return null;
}

const ExplorationMap = forwardRef<ExplorationMapHandle, ExplorationMapProps>(
  (
    {
      selectedFloat,
      floatTypeFilter,
      activeBasin,
      basinFloats,
      drawnRadius,
      drawCircleMode,
      onMapClick,
      onFloatClick,
      onCircleDrawn,
      onCircleModeHandled,
      onFloatsLoaded,
    },
    ref,
  ) => {
    const [isClient, setIsClient] = useState(false);
    const [mapInstance, setMapInstance] = useState<LeafletMap | null>(null);
    const [floats, setFloats] = useState<ActiveFloat[]>([]);
    const [basinPolygons, setBasinPolygons] = useState<BasinPolygonFeature[]>([]);
    const [loading, setLoading] = useState(true);
    const drawCircleRef = useRef<{ enable: () => void } | null>(null);

    useEffect(() => {
      setIsClient(true);
    }, []);

    useEffect(() => {
      let mounted = true;
      setLoading(true);
      getActiveFloats()
        .then((rows) => {
          if (!mounted) return;
          setFloats(rows);
          onFloatsLoaded?.(rows);
        })
        .catch(() => {
          if (!mounted) return;
          setFloats([]);
        })
        .finally(() => {
          if (!mounted) return;
          setLoading(false);
        });

      return () => {
        mounted = false;
      };
    }, [onFloatsLoaded]);

    useEffect(() => {
      let mounted = true;
      getBasinPolygons()
        .then((response) => {
          if (!mounted) return;
          setBasinPolygons(response.features);
        })
        .catch(() => {
          if (!mounted) return;
          setBasinPolygons([]);
        });

      return () => {
        mounted = false;
      };
    }, []);

    useImperativeHandle(ref, () => ({
      zoomIn: () => mapInstance?.zoomIn(),
      zoomOut: () => mapInstance?.zoomOut(),
      resetView: () => mapInstance?.setView(DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM),
      flyTo: (lat: number, lon: number, zoom = 6) => mapInstance?.flyTo([lat, lon], zoom),
    }), [mapInstance]);

    useEffect(() => {
      if (!mapInstance || !drawCircleMode) return;

      const handleCreated = (event: any) => {
        if (event.layerType !== "circle") return;
        const layer = event.layer as L.Circle;
        const center = layer.getLatLng();
        const radiusKm = layer.getRadius() / 1000;
        onCircleDrawn({
          center: { lat: center.lat, lon: center.lng },
          radius_km: radiusKm,
        });
        onCircleModeHandled();
      };

      const leafletDraw = (L as any).Draw;
      const createdEventName = leafletDraw?.Event?.CREATED ?? "draw:created";

      const circleTool = new leafletDraw.Circle(mapInstance, {
        shapeOptions: {
          color: "var(--color-ocean-primary)",
          fillColor: "var(--color-ocean-lighter)",
          fillOpacity: 0.2,
          weight: 2,
        },
      });
      drawCircleRef.current = circleTool;
      mapInstance.on(createdEventName, handleCreated);
      circleTool.enable();

      return () => {
        mapInstance.off(createdEventName, handleCreated);
      };
    }, [mapInstance, drawCircleMode, onCircleDrawn, onCircleModeHandled]);

    const cssVars = useMemo(() => {
      if (!isClient) {
        return {
          oceanPrimary: "var(--color-ocean-primary)",
          coral: "var(--color-coral)",
          surface: "var(--color-bg-surface)",
        };
      }
      const root = getComputedStyle(document.documentElement);
      return {
        oceanPrimary: root.getPropertyValue("--color-ocean-primary").trim() || "var(--color-ocean-primary)",
        coral: root.getPropertyValue("--color-coral").trim() || "var(--color-coral)",
        surface: root.getPropertyValue("--color-bg-surface").trim() || "var(--color-bg-surface)",
      };
    }, [isClient]);

    const baseFloats = useMemo(() => {
      if (activeBasin && basinFloats) {
        return basinFloats.map((row) => ({
          platform_number: row.platform_number,
          float_type: row.float_type,
          latitude: row.latitude,
          longitude: row.longitude,
          last_seen: row.last_seen,
        }));
      }
      return floats;
    }, [activeBasin, basinFloats, floats]);

    const visibleFloats = useMemo(() => {
      if (floatTypeFilter === "all") return baseFloats;
      return baseFloats.filter((row) => {
        const type = (row.float_type ?? "").toLowerCase();
        if (floatTypeFilter === "bgc") return type === "bgc";
        return type === "core";
      });
    }, [baseFloats, floatTypeFilter]);

    if (!isClient) {
      return (
        <div className="flex h-full w-full items-center justify-center bg-[var(--color-bg-surface)] text-[var(--color-text-secondary)]">
          Loading map…
        </div>
      );
    }

    return (
      <div className="relative h-full w-full">
        <MapContainer
          center={DEFAULT_MAP_CENTER}
          zoom={DEFAULT_MAP_ZOOM}
          style={{ height: "100%", width: "100%" }}
          scrollWheelZoom
          ref={setMapInstance}
        >
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />

          <MapClickHandler onMapClick={onMapClick} />

          {basinPolygons.map((feature) => {
            const regionName = feature.properties.region_name;
            const isActive = !!activeBasin && regionName === activeBasin;

            return (
              <GeoJSON
                key={`basin-${feature.properties.region_id}`}
                data={feature as any}
                style={{
                  color: cssVars.oceanPrimary,
                  weight: isActive ? 2 : 1,
                  opacity: isActive ? 1 : 0.15,
                  fill: true,
                  fillColor: "var(--color-ocean-lighter)",
                  fillOpacity: isActive ? 0.3 : 0,
                }}
              >
                <Tooltip direction="top" offset={[0, -4]}>
                  <div className="text-xs">{regionName}</div>
                </Tooltip>
              </GeoJSON>
            );
          })}

          {drawnRadius && (
            <Circle
              center={[drawnRadius.center.lat, drawnRadius.center.lon]}
              radius={drawnRadius.radius_km * 1000}
              pathOptions={{
                color: cssVars.oceanPrimary,
                fillColor: cssVars.oceanPrimary,
                fillOpacity: 0.15,
                weight: 2,
              }}
            >
              <Tooltip direction="top" offset={[0, -4]} permanent>
                <div className="text-xs">{drawnRadius.radius_km.toFixed(1)} km</div>
              </Tooltip>
            </Circle>
          )}

          <MarkerClusterGroup chunkedLoading>
            {visibleFloats.map((row) => {
              if (row.latitude === null || row.longitude === null) return null;

              const type = (row.float_type ?? "").toLowerCase();
              const markerColor = type === "bgc" ? cssVars.coral : cssVars.oceanPrimary;
              const isSelected = selectedFloat === row.platform_number;

              return (
                <CircleMarker
                  key={row.platform_number}
                  center={[row.latitude, row.longitude]}
                  radius={isSelected ? 10 : 6}
                  pathOptions={{
                    color: isSelected ? cssVars.surface : markerColor,
                    weight: isSelected ? 2 : 1,
                    fillColor: markerColor,
                    fillOpacity: 0.9,
                  }}
                  eventHandlers={{
                    click: () => onFloatClick(row.platform_number),
                  }}
                >
                  <Tooltip direction="top" offset={[0, -4]}>
                    <div className="text-xs">
                      <div>{row.platform_number}</div>
                      <div className="opacity-80">{row.float_type ?? "unknown"}</div>
                    </div>
                  </Tooltip>
                </CircleMarker>
              );
            })}
          </MarkerClusterGroup>
        </MapContainer>

        {loading && (
          <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-black/10">
            <div className="rounded-md bg-[var(--color-bg-surface)] px-3 py-2 text-sm text-[var(--color-text-secondary)] shadow-sm">
              Loading active floats…
            </div>
          </div>
        )}
      </div>
    );
  },
);

ExplorationMap.displayName = "ExplorationMap";

export default ExplorationMap;

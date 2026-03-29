"use client";

/**
 * RegionSelector — Leaflet map with draw tools for geographic selection (Feature 6, Phase 6).
 *
 * Allows the user to draw a rectangle or polygon on the map.
 * On draw completion, emits GeoJSON via `onRegionSelect` callback.
 * Built standalone — not auto-rendered by VisualizationPanel.
 * Reserved for Feature 7 integration.
 *
 * Hard Rule 3: OpenStreetMap attribution MUST be displayed.
 * Hard Rule 4: Leaflet CSS imported in layout.tsx, NOT here.
 * Hard Rule 6: Map only initialises client-side.
 *
 * @requires Leaflet CSS imported globally in `app/layout.tsx`.
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { MapContainer, TileLayer, FeatureGroup } from "react-leaflet";
import { EditControl } from "react-leaflet-draw";
import { MapPin, Trash2 } from "lucide-react";
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM } from "@/lib/colorscales";
import type { RegionSelectorProps } from "@/types/visualization";
import type { FeatureGroup as LeafletFeatureGroup, Layer } from "leaflet";

interface DrawCreatedEvent {
    layer: Layer & {
        toGeoJSON: () => GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.MultiPolygon>;
    };
}

// ── Component ─────────────────────────────────────────────────────────────

export default function RegionSelector({
    onRegionSelect,
    center = DEFAULT_MAP_CENTER,
    zoom = DEFAULT_MAP_ZOOM,
}: RegionSelectorProps) {
    const [isClient, setIsClient] = useState(false);
    const [hasRegion, setHasRegion] = useState(false);
    const [drawnGeoJSON, setDrawnGeoJSON] = useState<
        GeoJSON.Polygon | GeoJSON.MultiPolygon | null
    >(null);
    const featureGroupRef = useRef<LeafletFeatureGroup | null>(null);

    useEffect(() => setIsClient(true), []);

    // Handle draw created
    const handleCreated = useCallback(
        (e: DrawCreatedEvent) => {
            // Remove any previously drawn shapes (one active region at a time)
            if (featureGroupRef.current) {
                const layers = featureGroupRef.current.getLayers();
                // Keep only the most recent layer — remove all others
                if (layers.length > 1) {
                    for (let i = 0; i < layers.length - 1; i++) {
                        featureGroupRef.current.removeLayer(layers[i]);
                    }
                }
            }

            const layer = e.layer;
            const geo = layer.toGeoJSON?.();
            if (geo?.geometry) {
                const geometry = geo.geometry as GeoJSON.Polygon | GeoJSON.MultiPolygon;
                setDrawnGeoJSON(geometry);
                setHasRegion(true);
                onRegionSelect(geometry);
            }
        },
        [onRegionSelect],
    );

    // Clear drawn region
    const handleClear = useCallback(() => {
        if (featureGroupRef.current) {
            featureGroupRef.current.clearLayers();
        }
        setHasRegion(false);
        setDrawnGeoJSON(null);
    }, []);

    // "Use this region" button
    const handleUseRegion = useCallback(() => {
        if (drawnGeoJSON) {
            onRegionSelect(drawnGeoJSON);
        }
    }, [drawnGeoJSON, onRegionSelect]);

    if (!isClient) {
        return (
            <div
                className="flex h-[400px] w-full items-center justify-center rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)]"
                role="status"
                aria-label="Loading map"
            >
                <div className="flex flex-col items-center gap-2 text-[var(--color-text-muted)]">
                    <div className="h-6 w-6 animate-spin rounded-full border-2 border-current border-t-transparent" />
                    <span className="text-xs">Loading map…</span>
                </div>
            </div>
        );
    }

    return (
        <div className="w-full overflow-hidden rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)]">
            <div
                className="relative h-[400px] w-full"
                role="img"
                aria-label="Interactive map for geographic region selection"
            >
                <MapContainer
                    center={center}
                    zoom={zoom}
                    style={{ height: "100%", width: "100%" }}
                    scrollWheelZoom
                >
                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />

                    <FeatureGroup
                        ref={(ref) => {
                            featureGroupRef.current = ref as LeafletFeatureGroup | null;
                        }}
                    >
                        <EditControl
                            position="topright"
                            onCreated={handleCreated}
                            draw={{
                                rectangle: {
                                    shapeOptions: {
                                        fillColor: "#0080ff",
                                        fillOpacity: 0.2,
                                        color: "#0080ff",
                                        weight: 2,
                                    },
                                },
                                polygon: {
                                    shapeOptions: {
                                        fillColor: "#0080ff",
                                        fillOpacity: 0.2,
                                        color: "#0080ff",
                                        weight: 2,
                                    },
                                },
                                polyline: false,
                                circle: false,
                                circlemarker: false,
                                marker: false,
                            }}
                            edit={{
                                remove: true,
                            }}
                        />
                    </FeatureGroup>
                </MapContainer>
            </div>

            {/* Action buttons */}
            {hasRegion && (
                <div className="flex items-center justify-between px-4 py-2.5 border-t border-[var(--color-border-subtle)]">
                    <span className="flex items-center gap-1.5 text-xs text-[var(--color-text-secondary)]">
                        <MapPin size={14} className="text-[var(--color-ocean-primary)]" />
                        Region selected
                    </span>
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleClear}
                            className="flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-normal hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-danger)]"
                            aria-label="Clear selected region"
                        >
                            <Trash2 size={14} />
                            <span>Clear</span>
                        </button>
                        <button
                            onClick={handleUseRegion}
                            className="flex items-center gap-1.5 rounded-md bg-[var(--color-ocean-primary)] px-4 py-1.5 text-xs font-medium text-[var(--color-text-inverse)] transition-colors duration-normal hover:bg-[var(--color-ocean-light)]"
                            aria-label="Use this region for querying"
                        >
                            <span>Use this region</span>
                        </button>
                    </div>
                </div>
            )}
        </div>
    );
}

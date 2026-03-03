"use client";

/**
 * FloatPositionMap — Leaflet map with clustered float markers (Feature 6, Phase 6).
 *
 * Renders float positions as circle markers, clustered via react-leaflet-cluster.
 * Color-coded by a variable value using cmocean colorscales when `colorVariable`
 * is provided.
 *
 * Hard Rule 3: OpenStreetMap attribution MUST be displayed.
 * Hard Rule 4: Leaflet CSS imported in layout.tsx, NOT here.
 * Hard Rule 6: Map only initialises client-side (useEffect + useState guard).
 *
 * @requires Leaflet CSS imported globally in `app/layout.tsx`.
 */

import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
    MapContainer,
    TileLayer,
    CircleMarker,
    Popup,
    useMap,
} from "react-leaflet";
import MarkerClusterGroup from "react-leaflet-cluster";
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM, COLORSCALE_FOR_VARIABLE } from "@/lib/colorscales";
import type { FloatPositionMapProps, ChartRow } from "@/types/visualization";
import type { LatLngBoundsLiteral } from "leaflet";

// ── Color interpolation helper ────────────────────────────────────────────

function hexToRgb(hex: string): [number, number, number] {
    const h = hex.replace("#", "");
    return [
        parseInt(h.substring(0, 2), 16),
        parseInt(h.substring(2, 4), 16),
        parseInt(h.substring(4, 6), 16),
    ];
}

function interpolateColor(
    stops: [number, string][],
    fraction: number,
): string {
    const t = Math.max(0, Math.min(1, fraction));
    let lower = stops[0];
    let upper = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i++) {
        if (t >= stops[i][0] && t <= stops[i + 1][0]) {
            lower = stops[i];
            upper = stops[i + 1];
            break;
        }
    }
    const range = upper[0] - lower[0];
    const localT = range === 0 ? 0 : (t - lower[0]) / range;
    const [r1, g1, b1] = hexToRgb(lower[1]);
    const [r2, g2, b2] = hexToRgb(upper[1]);
    const r = Math.round(r1 + (r2 - r1) * localT);
    const g = Math.round(g1 + (g2 - g1) * localT);
    const b = Math.round(b1 + (b2 - b1) * localT);
    return `rgb(${r},${g},${b})`;
}

// ── Auto-fit bounds component ─────────────────────────────────────────────

function FitBounds({ bounds }: { bounds: LatLngBoundsLiteral }) {
    const map = useMap();
    useEffect(() => {
        if (bounds.length > 0) {
            map.fitBounds(bounds, { padding: [20, 20], maxZoom: 12 });
        }
    }, [map, bounds]);
    return null;
}

// ── Default marker color ──────────────────────────────────────────────────

const OCEAN_BLUE = "rgb(30, 100, 180)";

// ── Component ─────────────────────────────────────────────────────────────

export default function FloatPositionMap({
    rows,
    columns,
    colorVariable,
}: FloatPositionMapProps) {
    // Hard Rule 6: only render map client-side
    const [isClient, setIsClient] = useState(false);
    useEffect(() => setIsClient(true), []);

    const lowerCols = useMemo(() => columns.map((c) => c.toLowerCase()), [columns]);

    const findCol = useCallback(
        (name: string) => {
            const idx = lowerCols.findIndex((c) => c === name);
            return idx >= 0 ? columns[idx] : null;
        },
        [columns, lowerCols],
    );

    const latKey = findCol("latitude") ?? findCol("lat");
    const lonKey = findCol("longitude") ?? findCol("lon") ?? findCol("lng");

    // Color variable resolution
    const colorKey = useMemo(() => {
        if (!colorVariable) return null;
        return findCol(colorVariable.toLowerCase());
    }, [colorVariable, findCol]);

    // Determine colorscale for the variable
    const colorscaleStops = useMemo(() => {
        if (!colorKey || !colorVariable) return null;
        const scale = COLORSCALE_FOR_VARIABLE[colorVariable.toLowerCase()];
        return scale ?? null;
    }, [colorKey, colorVariable]);

    // Value range for color mapping
    const { minVal, maxVal } = useMemo(() => {
        if (!colorKey) return { minVal: 0, maxVal: 1 };
        const vals = rows
            .map((r) => r[colorKey])
            .filter((v): v is number => typeof v === "number");
        if (vals.length === 0) return { minVal: 0, maxVal: 1 };
        return { minVal: Math.min(...vals), maxVal: Math.max(...vals) };
    }, [rows, colorKey]);

    // Compute bounds
    const bounds = useMemo((): LatLngBoundsLiteral => {
        if (!latKey || !lonKey) return [[DEFAULT_MAP_CENTER[0], DEFAULT_MAP_CENTER[1]]];
        const coords: [number, number][] = [];
        for (const row of rows) {
            const lat = row[latKey];
            const lon = row[lonKey];
            if (typeof lat === "number" && typeof lon === "number") {
                coords.push([lat, lon]);
            }
        }
        if (coords.length === 0) return [[DEFAULT_MAP_CENTER[0], DEFAULT_MAP_CENTER[1]]];
        const lats = coords.map((c) => c[0]);
        const lons = coords.map((c) => c[1]);
        return [
            [Math.min(...lats) - 0.1, Math.min(...lons) - 0.1],
            [Math.max(...lats) + 0.1, Math.max(...lons) + 0.1],
        ];
    }, [rows, latKey, lonKey]);

    // Get color for a row
    const getColor = useCallback(
        (row: ChartRow): string => {
            if (!colorKey || !colorscaleStops) return OCEAN_BLUE;
            const val = row[colorKey];
            if (typeof val !== "number") return OCEAN_BLUE;
            const range = maxVal - minVal;
            const fraction = range === 0 ? 0.5 : (val - minVal) / range;
            return interpolateColor(colorscaleStops as [number, string][], fraction);
        },
        [colorKey, colorscaleStops, minVal, maxVal],
    );

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
                aria-label="Map showing float positions"
            >
                <MapContainer
                    center={DEFAULT_MAP_CENTER}
                    zoom={DEFAULT_MAP_ZOOM}
                    style={{ height: "100%", width: "100%" }}
                    scrollWheelZoom
                >
                    <TileLayer
                        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                    />
                    <FitBounds bounds={bounds} />

                    <MarkerClusterGroup chunkedLoading>
                        {rows.map((row, i) => {
                            if (!latKey || !lonKey) return null;
                            const lat = row[latKey];
                            const lon = row[lonKey];
                            if (typeof lat !== "number" || typeof lon !== "number") return null;

                            const color = getColor(row);
                            return (
                                <CircleMarker
                                    key={i}
                                    center={[lat, lon]}
                                    radius={6}
                                    pathOptions={{
                                        fillColor: color,
                                        fillOpacity: 0.85,
                                        color: "rgba(255,255,255,0.6)",
                                        weight: 1,
                                    }}
                                >
                                    <Popup>
                                        <div className="max-h-48 overflow-auto font-body text-xs">
                                            <table className="w-full border-collapse">
                                                <tbody>
                                                    {columns.map((col) => (
                                                        <tr key={col} className="border-b border-gray-200 last:border-0">
                                                            <td className="pr-2 py-0.5 font-medium text-gray-600">
                                                                {col}
                                                            </td>
                                                            <td className="py-0.5 text-gray-800">
                                                                {String(row[col] ?? "—")}
                                                            </td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </div>
                                    </Popup>
                                </CircleMarker>
                            );
                        })}
                    </MarkerClusterGroup>
                </MapContainer>
            </div>

            {/* Colorbar legend */}
            {colorKey && colorscaleStops && (
                <div className="flex items-center gap-3 px-4 py-2 border-t border-[var(--color-border-subtle)]">
                    <span className="text-xs font-medium text-[var(--color-text-secondary)]">
                        {colorVariable}
                    </span>
                    <div className="flex-1 flex items-center gap-1">
                        <span className="text-[10px] text-[var(--color-text-muted)]">
                            {minVal.toFixed(1)}
                        </span>
                        <div
                            className="flex-1 h-3 rounded-full"
                            style={{
                                background: `linear-gradient(to right, ${(colorscaleStops as [number, string][])
                                    .map(([pos, col]) => `${col} ${pos * 100}%`)
                                    .join(", ")})`,
                            }}
                        />
                        <span className="text-[10px] text-[var(--color-text-muted)]">
                            {maxVal.toFixed(1)}
                        </span>
                    </div>
                </div>
            )}
        </div>
    );
}

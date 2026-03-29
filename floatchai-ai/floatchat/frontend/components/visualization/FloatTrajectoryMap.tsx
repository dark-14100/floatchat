"use client";

/**
 * FloatTrajectoryMap — Leaflet trajectory polylines (Feature 6, Phase 6).
 *
 * Renders float paths as temporal-gradient polylines (blue→red).
 * Each unique platform_number gets its own polyline ordered by timestamp.
 * Start marker: blue, end marker: red with white stroke.
 *
 * Hard Rule 3: OpenStreetMap attribution MUST be displayed.
 * Hard Rule 4: Leaflet CSS imported in layout.tsx, NOT here.
 * Hard Rule 6: Map only initialises client-side.
 *
 * @requires Leaflet CSS imported globally in `app/layout.tsx`.
 */

import React, { useState, useEffect, useMemo, useCallback } from "react";
import {
    MapContainer,
    TileLayer,
    Polyline,
    CircleMarker,
    Popup,
    useMap,
} from "react-leaflet";
import { DEFAULT_MAP_CENTER, DEFAULT_MAP_ZOOM } from "@/lib/colorscales";
import type { FloatTrajectoryMapProps, ChartRow } from "@/types/visualization";
import type { LatLngBoundsLiteral, LatLngTuple } from "leaflet";

// ── Temporal color gradient helper ────────────────────────────────────────

function temporalColor(fraction: number): string {
    // Linear interpolation: rgb(0, 80, 200) at t=0  →  rgb(200, 30, 30) at t=1
    const t = Math.max(0, Math.min(1, fraction));
    const r = Math.round(0 + (200 - 0) * t);
    const g = Math.round(80 + (30 - 80) * t);
    const b = Math.round(200 + (30 - 200) * t);
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

// ── Types ─────────────────────────────────────────────────────────────────

interface TrajectoryPoint {
    lat: number;
    lon: number;
    timestamp: string | number;
    row: ChartRow;
}

interface FloatTrajectory {
    floatId: string;
    points: TrajectoryPoint[];
}

// ── Component ─────────────────────────────────────────────────────────────

export default function FloatTrajectoryMap({
    rows,
    columns,
    floatIdColumn,
}: FloatTrajectoryMapProps) {
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
    const timestampKey = findCol("juld_timestamp") ?? findCol("juld") ?? findCol("timestamp");
    const platformKey = floatIdColumn
        ? (findCol(floatIdColumn.toLowerCase()) ?? findCol("platform_number"))
        : findCol("platform_number");

    // Group rows into trajectories by float, sorted by time
    const trajectories = useMemo((): FloatTrajectory[] => {
        if (!latKey || !lonKey) return [];

        const groups: Record<string, TrajectoryPoint[]> = {};
        for (const row of rows) {
            const lat = row[latKey];
            const lon = row[lonKey];
            if (typeof lat !== "number" || typeof lon !== "number") continue;

            const fid = platformKey ? String(row[platformKey] ?? "unknown") : "__single";
            const ts = timestampKey ? (row[timestampKey] as string | number) : 0;

            if (!groups[fid]) groups[fid] = [];
            groups[fid].push({ lat, lon, timestamp: ts, row });
        }

        return Object.entries(groups).map(([floatId, points]) => ({
            floatId,
            points: points.sort((a, b) => {
                const ta = new Date(a.timestamp).getTime();
                const tb = new Date(b.timestamp).getTime();
                return ta - tb;
            }),
        }));
    }, [rows, latKey, lonKey, timestampKey, platformKey]);

    // Bounds
    const bounds = useMemo((): LatLngBoundsLiteral => {
        const coords: [number, number][] = [];
        for (const traj of trajectories) {
            for (const pt of traj.points) {
                coords.push([pt.lat, pt.lon]);
            }
        }
        if (coords.length === 0) return [[DEFAULT_MAP_CENTER[0], DEFAULT_MAP_CENTER[1]]];
        const lats = coords.map((c) => c[0]);
        const lons = coords.map((c) => c[1]);
        return [
            [Math.min(...lats) - 0.1, Math.min(...lons) - 0.1],
            [Math.max(...lats) + 0.1, Math.max(...lons) + 0.1],
        ];
    }, [trajectories]);

    // Format timestamp for display
    const formatTs = useCallback((ts: string | number): string => {
        try {
            return new Date(ts).toLocaleDateString("en-US", {
                year: "numeric",
                month: "short",
                day: "numeric",
            });
        } catch {
            return String(ts);
        }
    }, []);

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
                aria-label="Map showing float trajectories over time"
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

                    {trajectories.map((traj) => {
                        // Downsample long trajectories to 200 points for performance
                        let pts = traj.points;
                        if (pts.length > 500) {
                            const step = Math.ceil(pts.length / 200);
                            const sampled: TrajectoryPoint[] = [];
                            for (let i = 0; i < pts.length; i += step) sampled.push(pts[i]);
                            // Always include the last point
                            if (sampled[sampled.length - 1] !== pts[pts.length - 1]) {
                                sampled.push(pts[pts.length - 1]);
                            }
                            pts = sampled;
                        }

                        const numPoints = pts.length;

                        return (
                            <React.Fragment key={traj.floatId}>
                                {/* Temporal gradient: one segment per pair of consecutive points */}
                                {pts.slice(0, -1).map((pt, segIdx) => {
                                    const nextPt = pts[segIdx + 1];
                                    const fraction = numPoints <= 1 ? 0 : segIdx / (numPoints - 1);
                                    const color = temporalColor(fraction);
                                    const positions: LatLngTuple[] = [
                                        [pt.lat, pt.lon],
                                        [nextPt.lat, nextPt.lon],
                                    ];

                                    return (
                                        <Polyline
                                            key={`${traj.floatId}-seg-${segIdx}`}
                                            positions={positions}
                                            pathOptions={{ color, weight: 3, opacity: 0.85 }}
                                        />
                                    );
                                })}

                                {/* Intermediate markers */}
                                {pts.slice(1, -1).map((pt, idx) => {
                                    const fraction = numPoints <= 1 ? 0.5 : (idx + 1) / (numPoints - 1);
                                    const color = temporalColor(fraction);
                                    return (
                                        <CircleMarker
                                            key={`${traj.floatId}-mid-${idx}`}
                                            center={[pt.lat, pt.lon]}
                                            radius={4}
                                            pathOptions={{
                                                fillColor: color,
                                                fillOpacity: 0.9,
                                                color,
                                                weight: 1,
                                            }}
                                        >
                                            <Popup>
                                                <div className="font-body text-xs">
                                                    <p className="font-medium">
                                                        Float {traj.floatId}
                                                    </p>
                                                    <p>{formatTs(pt.timestamp)}</p>
                                                    <p>
                                                        {pt.lat.toFixed(3)}°, {pt.lon.toFixed(3)}°
                                                    </p>
                                                </div>
                                            </Popup>
                                        </CircleMarker>
                                    );
                                })}

                                {/* Start marker — blue, larger */}
                                {pts.length > 0 && (
                                    <CircleMarker
                                        center={[pts[0].lat, pts[0].lon]}
                                        radius={8}
                                        pathOptions={{
                                            fillColor: "rgb(0, 80, 200)",
                                            fillOpacity: 1,
                                            color: "transparent",
                                            weight: 0,
                                        }}
                                    >
                                        <Popup>
                                            <div className="font-body text-xs">
                                                <p className="font-semibold text-blue-600">
                                                    ▶ Start — Float {traj.floatId}
                                                </p>
                                                <p>{formatTs(pts[0].timestamp)}</p>
                                                <p>
                                                    {pts[0].lat.toFixed(3)}°, {pts[0].lon.toFixed(3)}°
                                                </p>
                                            </div>
                                        </Popup>
                                    </CircleMarker>
                                )}

                                {/* End marker — red, white stroke */}
                                {pts.length > 1 && (
                                    <CircleMarker
                                        center={[pts[pts.length - 1].lat, pts[pts.length - 1].lon]}
                                        radius={8}
                                        pathOptions={{
                                            fillColor: "rgb(200, 30, 30)",
                                            fillOpacity: 1,
                                            color: "#ffffff",
                                            weight: 2,
                                        }}
                                    >
                                        <Popup>
                                            <div className="font-body text-xs">
                                                <p className="font-semibold text-red-600">
                                                    ■ End — Float {traj.floatId}
                                                </p>
                                                <p>{formatTs(pts[pts.length - 1].timestamp)}</p>
                                                <p>
                                                    {pts[pts.length - 1].lat.toFixed(3)}°,{" "}
                                                    {pts[pts.length - 1].lon.toFixed(3)}°
                                                </p>
                                            </div>
                                        </Popup>
                                    </CircleMarker>
                                )}
                            </React.Fragment>
                        );
                    })}
                </MapContainer>
            </div>

            {/* Legend */}
            {trajectories.length > 0 && (
                <div className="flex items-center gap-3 px-4 py-2 border-t border-[var(--color-border-subtle)]">
                    <div className="flex items-center gap-1.5">
                        <div className="h-3 w-3 rounded-full bg-[rgb(0,80,200)]" />
                        <span className="text-[10px] text-[var(--color-text-muted)]">Start</span>
                    </div>
                    <div
                        className="flex-1 h-2 rounded-full"
                        style={{
                            background: "linear-gradient(to right, rgb(0,80,200), rgb(100,55,115), rgb(200,30,30))",
                        }}
                    />
                    <div className="flex items-center gap-1.5">
                        <div className="h-3 w-3 rounded-full bg-[rgb(200,30,30)] ring-2 ring-white" />
                        <span className="text-[10px] text-[var(--color-text-muted)]">End</span>
                    </div>
                    {trajectories.length > 1 && (
                        <span className="ml-2 text-[10px] text-[var(--color-text-muted)]">
                            {trajectories.length} floats
                        </span>
                    )}
                </div>
            )}
        </div>
    );
}

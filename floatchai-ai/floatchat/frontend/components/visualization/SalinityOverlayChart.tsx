"use client";

/**
 * SalinityOverlayChart — Dual-axis temperature + salinity overlay (Feature 6, Phase 5).
 *
 * Temperature on primary X-axis (bottom), salinity on secondary X-axis (top).
 * Y-axis = pressure, inverted (Hard Rule 2).
 *
 * Includes a toggle button to switch to T-S diagram view.
 * The T-S diagram import MUST use next/dynamic with { ssr: false } (Hard Rule 1).
 *
 * Hard Rule 5: Colorscales imported from lib/colorscales.ts.
 * Hard Rule 10: Export filenames include ISO timestamp.
 */

import React, { useState, useRef, useCallback, useMemo } from "react";
import Plot from "react-plotly.js";
import Plotly from "plotly.js-dist-min";
import dynamic from "next/dynamic";
import { Download, ToggleLeft, ToggleRight } from "lucide-react";
import type { SalinityOverlayChartProps, ChartRow } from "@/types/visualization";

// T-S diagram loaded dynamically (Hard Rule 1)
const TSdiagram = dynamic(() => import("./TSdiagram"), { ssr: false });

// ── Distinct colors per float ─────────────────────────────────────────────

const TEMP_COLORS = [
    "#D94F3D", "#E8785A", "#C94040", "#FF6B4A", "#E06040",
];
const SAL_COLORS = [
    "#1B7A9E", "#4BAAC8", "#2D7A9A", "#0D4F6B", "#7FCCE0",
];

// ── Component ─────────────────────────────────────────────────────────────

export default function SalinityOverlayChart({
    rows,
    columns,
    startAsTSDiagram = false,
    colorscale,
}: SalinityOverlayChartProps) {
    const [showTS, setShowTS] = useState(startAsTSDiagram);
    const plotRef = useRef<HTMLDivElement>(null);

    // Column resolution
    const lowerCols = useMemo(() => columns.map((c) => c.toLowerCase()), [columns]);
    const findCol = useCallback(
        (name: string) => {
            const idx = lowerCols.findIndex((c) => c === name);
            return idx >= 0 ? columns[idx] : null;
        },
        [columns, lowerCols],
    );

    const tempKey = findCol("temperature") ?? findCol("temp");
    const salKey = findCol("salinity") ?? findCol("psal");
    const pressureKey = findCol("pressure") ?? findCol("pres");
    const platformKey = findCol("platform_number");

    // Group by float
    const groupedByFloat = useMemo(() => {
        const groups: Record<string, ChartRow[]> = {};
        for (const row of rows) {
            const key = platformKey
                ? String(row[platformKey] ?? "unknown")
                : "__single";
            if (!groups[key]) groups[key] = [];
            groups[key].push(row);
        }
        return groups;
    }, [rows, platformKey]);

    const floatIds = Object.keys(groupedByFloat);
    const isMultiFloat = floatIds.length > 1;

    // Build Plotly traces
    const traces = useMemo(() => {
        const result: Plotly.Data[] = [];

        for (let fi = 0; fi < floatIds.length; fi++) {
            const fid = floatIds[fi];
            const fRows = groupedByFloat[fid];
            const pressures = pressureKey ? fRows.map((r) => r[pressureKey] as number) : [];

            // Temperature trace (primary X-axis, bottom)
            if (tempKey) {
                const temps = fRows.map((r) => r[tempKey] as number);
                result.push({
                    x: temps,
                    y: pressures,
                    type: rows.length > 10_000 ? "scattergl" : "scatter",
                    mode: "lines+markers",
                    name: isMultiFloat ? `Temp — ${fid}` : "Temperature",
                    marker: {
                        color: TEMP_COLORS[fi % TEMP_COLORS.length],
                        size: 4,
                        opacity: 0.85,
                    },
                    line: {
                        color: TEMP_COLORS[fi % TEMP_COLORS.length],
                        width: 2,
                    },
                    xaxis: "x",
                    yaxis: "y",
                    hovertemplate: `Temperature: %{x:.2f} °C<br>Pressure: %{y} dbar<extra>${isMultiFloat ? fid : ""}</extra>`,
                    legendgroup: isMultiFloat ? fid : "temp",
                } as Plotly.Data);
            }

            // Salinity trace (secondary X-axis, top)
            if (salKey) {
                const sals = fRows.map((r) => r[salKey] as number);
                result.push({
                    x: sals,
                    y: pressures,
                    type: rows.length > 10_000 ? "scattergl" : "scatter",
                    mode: "lines+markers",
                    name: isMultiFloat ? `Sal — ${fid}` : "Salinity",
                    marker: {
                        color: SAL_COLORS[fi % SAL_COLORS.length],
                        size: 4,
                        opacity: 0.85,
                    },
                    line: {
                        color: SAL_COLORS[fi % SAL_COLORS.length],
                        width: 2,
                        dash: "dash",
                    },
                    xaxis: "x2",
                    yaxis: "y",
                    hovertemplate: `Salinity: %{x:.2f} PSU<br>Pressure: %{y} dbar<extra>${isMultiFloat ? fid : ""}</extra>`,
                    legendgroup: isMultiFloat ? fid : "sal",
                } as Plotly.Data);
            }
        }

        return result;
    }, [floatIds, groupedByFloat, pressureKey, tempKey, salKey, isMultiFloat, rows.length]);

    // Layout
    const layout = useMemo((): Partial<Plotly.Layout> => ({
        autosize: true,
        height: 480,
        margin: { t: 55, r: 30, b: 55, l: 70 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { family: "DM Sans, system-ui, sans-serif", size: 12, color: "#8BA5BC" },
        showlegend: true,
        legend: {
            orientation: "h",
            yanchor: "bottom",
            y: 1.08,
            xanchor: "right",
            x: 1,
            font: { size: 11 },
            bgcolor: "transparent",
        },
        yaxis: {
            title: { text: "Pressure (dbar)", font: { size: 12 } },
            autorange: "reversed", // Hard Rule 2
            gridcolor: "rgba(139, 165, 188, 0.15)",
            zerolinecolor: "rgba(139, 165, 188, 0.2)",
            tickfont: { size: 11 },
        },
        xaxis: {
            title: { text: "Temperature (°C)", font: { size: 12, color: "#D94F3D" } },
            gridcolor: "rgba(139, 165, 188, 0.12)",
            zerolinecolor: "rgba(139, 165, 188, 0.2)",
            tickfont: { size: 11, color: "#D94F3D" },
            side: "bottom",
        },
        xaxis2: {
            title: { text: "Salinity (PSU)", font: { size: 12, color: "#1B7A9E" } },
            gridcolor: "rgba(139, 165, 188, 0.08)",
            tickfont: { size: 11, color: "#1B7A9E" },
            overlaying: "x",
            side: "top",
        },
    }), []);

    // Export
    const handleExport = useCallback(
        async (format: "png" | "svg") => {
            const gd = plotRef.current?.querySelector(".js-plotly-plot") as Plotly.PlotlyHTMLElement | null;
            if (!gd) return;
            const ts = new Date().toISOString().replace(/[:.]/g, "-");
            await Plotly.downloadImage(gd, {
                format,
                width: 1200,
                height: 800,
                filename: `floatchat_salinity_overlay_${ts}`,
            } as Plotly.DownloadImgopts);
        },
        [],
    );

    // ── T-S diagram toggle view ─────────────────────────────────────────────

    if (showTS) {
        return (
            <div className="relative w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3">
                {/* Toggle back button */}
                <div className="absolute right-4 top-3 z-10">
                    <button
                        onClick={() => setShowTS(false)}
                        className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-ocean-primary)] transition-colors duration-normal hover:bg-[var(--color-bg-subtle)]"
                        aria-label="Switch to overlay view"
                    >
                        <ToggleLeft size={14} />
                        <span>Overlay View</span>
                    </button>
                </div>

                <TSdiagram
                    rows={rows}
                    columns={columns}
                    colorscale={colorscale}
                    showDensityContours={false}
                />
            </div>
        );
    }

    // ── Overlay view ────────────────────────────────────────────────────────

    return (
        <div
            ref={plotRef}
            className="relative w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3"
            role="img"
            aria-label="Salinity overlay chart showing temperature and salinity profiles against depth"
        >
            {/* Top actions: toggle + export */}
            <div className="absolute right-4 top-3 z-10 flex items-center gap-2">
                <button
                    onClick={() => setShowTS(true)}
                    className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium text-[var(--color-ocean-primary)] transition-colors duration-normal hover:bg-[var(--color-bg-subtle)]"
                    aria-label="Switch to T-S diagram view"
                >
                    <ToggleRight size={14} />
                    <span>T-S View</span>
                </button>
                <div className="h-4 w-px bg-[var(--color-border-subtle)]" />
                <button
                    onClick={() => handleExport("png")}
                    className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-normal hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-text-primary)]"
                    aria-label="Download chart as PNG"
                    title="Download PNG"
                >
                    <Download size={14} />
                    <span>PNG</span>
                </button>
                <button
                    onClick={() => handleExport("svg")}
                    className="flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-[var(--color-text-secondary)] transition-colors duration-normal hover:bg-[var(--color-bg-subtle)] hover:text-[var(--color-text-primary)]"
                    aria-label="Download chart as SVG"
                    title="Download SVG"
                >
                    <Download size={14} />
                    <span>SVG</span>
                </button>
            </div>

            <Plot
                data={traces}
                layout={layout}
                config={{ displayModeBar: false, responsive: true }}
                useResizeHandler
                style={{ width: "100%", height: "100%" }}
            />
        </div>
    );
}

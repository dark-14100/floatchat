"use client";

/**
 * TimeSeriesChart — Temporal line chart (Feature 6, Phase 5).
 *
 * X-axis = juld_timestamp formatted as dates, Y-axis = variable value.
 * Multi-float overlay with per-float color coding.
 * Optional depth (pressure) filter via maxPressure prop.
 *
 * Hard Rule 5: Colorscales imported from lib/colorscales.ts.
 * Hard Rule 8: scattergl for datasets > 10,000 points.
 * Hard Rule 10: Export filenames include ISO timestamp.
 */

import React, { useRef, useCallback, useMemo } from "react";
import Plot from "react-plotly.js";
import Plotly from "plotly.js-dist-min";
import { Download } from "lucide-react";
import type { TimeSeriesChartProps, ChartRow } from "@/types/visualization";

// ── Column label map ──────────────────────────────────────────────────────

const AXIS_LABELS: Record<string, string> = {
    temperature: "Temperature (°C)",
    temp: "Temperature (°C)",
    salinity: "Salinity (PSU)",
    psal: "Salinity (PSU)",
    dissolved_oxygen: "Dissolved Oxygen (μmol/kg)",
    chlorophyll: "Chlorophyll-a (mg/m³)",
    nitrate: "Nitrate (μmol/kg)",
    ph: "pH",
};

function label(col: string): string {
    return AXIS_LABELS[col.toLowerCase()] ?? col;
}

// ── 10 distinct float colors ──────────────────────────────────────────────

const FLOAT_COLORS = [
    "#1B7A9E", "#E8785A", "#7ECBA3", "#C9A96E", "#4BAAC8",
    "#D94F3D", "#5BA882", "#7B9DB8", "#A8D8E8", "#0D4F6B",
];

// ── Variable candidate list ──────────────────────────────────────────────

const VARIABLE_CANDIDATES = [
    "temperature", "temp", "salinity", "psal",
    "dissolved_oxygen", "chlorophyll", "nitrate", "ph",
];

// ── Component ─────────────────────────────────────────────────────────────

export default function TimeSeriesChart({
    rows,
    columns,
    maxPressure,
}: TimeSeriesChartProps) {
    const plotRef = useRef<HTMLDivElement>(null);

    const lowerCols = useMemo(() => columns.map((c) => c.toLowerCase()), [columns]);

    const findCol = useCallback(
        (name: string) => {
            const idx = lowerCols.findIndex((c) => c === name);
            return idx >= 0 ? columns[idx] : null;
        },
        [columns, lowerCols],
    );

    const timestampKey = findCol("juld_timestamp") ?? findCol("juld") ?? findCol("timestamp");
    const pressureKey = findCol("pressure") ?? findCol("pres");
    const platformKey = findCol("platform_number");

    // Determine which variable to plot
    const variableKey = useMemo(() => {
        for (const v of VARIABLE_CANDIDATES) {
            const found = findCol(v);
            if (found) return found;
        }
        // Fallback: first column that isn't a known non-variable
        const skip = new Set([
            "juld_timestamp", "juld", "timestamp", "pressure", "pres",
            "platform_number", "latitude", "longitude", "cycle_number",
        ]);
        for (const col of columns) {
            if (!skip.has(col.toLowerCase())) return col;
        }
        return null;
    }, [columns, findCol]);

    // Filter by maxPressure if specified
    const filteredRows = useMemo(() => {
        if (maxPressure === undefined || !pressureKey) return rows;
        return rows.filter((r) => {
            const p = r[pressureKey];
            return typeof p === "number" && p < maxPressure;
        });
    }, [rows, maxPressure, pressureKey]);

    const useGL = filteredRows.length > 10_000;
    const traceType = useGL ? "scattergl" : "scatter";

    // Group by platform_number
    const groupedByFloat = useMemo(() => {
        const groups: Record<string, ChartRow[]> = {};
        for (const row of filteredRows) {
            const key = platformKey
                ? String(row[platformKey] ?? "unknown")
                : "__single";
            if (!groups[key]) groups[key] = [];
            groups[key].push(row);
        }
        return groups;
    }, [filteredRows, platformKey]);

    const floatIds = Object.keys(groupedByFloat);

    // Build traces
    const traces = useMemo(() => {
        if (!timestampKey || !variableKey) return [];

        return floatIds.map((fid, fi) => {
            const fRows = groupedByFloat[fid];

            // Sort by timestamp
            const sorted = [...fRows].sort((a, b) => {
                const ta = new Date(a[timestampKey] as string | number).getTime();
                const tb = new Date(b[timestampKey] as string | number).getTime();
                return ta - tb;
            });

            const dates = sorted.map((r) => {
                const v = r[timestampKey];
                try {
                    return new Date(v as string | number).toISOString().split("T")[0];
                } catch {
                    return String(v);
                }
            });
            const values = sorted.map((r) => r[variableKey] as number);

            return {
                x: dates,
                y: values,
                type: traceType as Plotly.PlotType,
                mode: "lines+markers" as const,
                name: fid === "__single" ? label(variableKey) : `Float ${fid}`,
                marker: {
                    color: FLOAT_COLORS[fi % FLOAT_COLORS.length],
                    size: 4,
                    opacity: 0.8,
                },
                line: {
                    color: FLOAT_COLORS[fi % FLOAT_COLORS.length],
                    width: 2,
                },
                hovertemplate: `Date: %{x}<br>${label(variableKey)}: %{y:.2f}<extra>${fid === "__single" ? "" : `Float ${fid}`}</extra>`,
            } as Plotly.Data;
        });
    }, [floatIds, groupedByFloat, timestampKey, variableKey, traceType]);

    // Layout
    const layout = useMemo((): Partial<Plotly.Layout> => ({
        autosize: true,
        height: 420,
        margin: { t: 30, r: 30, b: 55, l: 65 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { family: "DM Sans, system-ui, sans-serif", size: 12, color: "#8BA5BC" },
        showlegend: floatIds.length > 1,
        legend: {
            orientation: "h",
            yanchor: "bottom",
            y: 1.02,
            xanchor: "right",
            x: 1,
            font: { size: 11 },
            bgcolor: "transparent",
        },
        xaxis: {
            title: { text: "Date", font: { size: 12 } },
            gridcolor: "rgba(139, 165, 188, 0.15)",
            zerolinecolor: "rgba(139, 165, 188, 0.2)",
            tickfont: { size: 11 },
        },
        yaxis: {
            title: { text: variableKey ? label(variableKey) : "", font: { size: 12 } },
            gridcolor: "rgba(139, 165, 188, 0.15)",
            zerolinecolor: "rgba(139, 165, 188, 0.2)",
            tickfont: { size: 11 },
        },
    }), [floatIds.length, variableKey]);

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
                filename: `floatchat_time_series_${ts}`,
            } as Plotly.DownloadImgopts);
        },
        [],
    );

    return (
        <div
            ref={plotRef}
            className="relative w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3"
            role="img"
            aria-label={`Time series chart${variableKey ? ` of ${label(variableKey)}` : ""}`}
        >
            {/* Export buttons */}
            <div className="absolute right-4 top-3 z-10 flex items-center gap-1">
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

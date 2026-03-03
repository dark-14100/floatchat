"use client";

/**
 * OceanProfileChart — Vertical ocean profile (Feature 6, Phase 5).
 *
 * X-axis = variable value, Y-axis = pressure (inverted — surface at top).
 * Supports dual X-axes when both temperature and salinity are present.
 * Color-coded by float ID (platform_number) for multi-float data.
 *
 * Hard Rule 2: Y-axis MUST be inverted (autorange: "reversed").
 * Hard Rule 5: Colorscales imported from lib/colorscales.ts — never inline.
 * Hard Rule 8: scattergl for datasets > 10,000 points.
 * Hard Rule 10: Export filenames include ISO timestamp.
 */

import React, { useRef, useCallback, useMemo } from "react";
import Plot from "react-plotly.js";
import Plotly from "plotly.js-dist-min";
import { Download } from "lucide-react";
import { THERMAL, getColorscale } from "@/lib/colorscales";
import type { OceanProfileChartProps, ChartRow } from "@/types/visualization";

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
    pressure: "Pressure (dbar)",
};

function label(col: string): string {
    return AXIS_LABELS[col.toLowerCase()] ?? col;
}

// ── Distinct colors for multi-float traces ────────────────────────────────

const FLOAT_COLORS = [
    "#1B7A9E", "#E8785A", "#7ECBA3", "#C9A96E", "#4BAAC8",
    "#D94F3D", "#5BA882", "#7B9DB8", "#A8D8E8", "#0D4F6B",
];

// ── Component ─────────────────────────────────────────────────────────────

export default function OceanProfileChart({
    rows,
    columns,
    variables,
    colorscale,
}: OceanProfileChartProps) {
    const plotRef = useRef<HTMLDivElement>(null);

    // Determine which variables to plot
    const lowerCols = useMemo(() => columns.map((c) => c.toLowerCase()), [columns]);
    const variableCols = useMemo(() => {
        if (variables && variables.length > 0) return variables;
        const candidates = ["temperature", "temp", "salinity", "psal", "dissolved_oxygen", "chlorophyll", "nitrate", "ph"];
        return lowerCols.filter((c) => candidates.includes(c));
    }, [variables, lowerCols]);

    // Find column index helper
    const colIdx = useCallback(
        (name: string) => lowerCols.indexOf(name.toLowerCase()),
        [lowerCols],
    );

    // Find pressure column
    const pressureKey = useMemo(() => {
        const pIdx = lowerCols.findIndex((c) => c === "pressure" || c === "pres");
        return pIdx >= 0 ? columns[pIdx] : null;
    }, [columns, lowerCols]);

    // Group rows by platform_number if present
    const platformIdx = colIdx("platform_number");
    const groupedByFloat = useMemo(() => {
        const groups: Record<string, ChartRow[]> = {};
        for (const row of rows) {
            const key = platformIdx >= 0
                ? String(row[columns[platformIdx]] ?? "unknown")
                : "__single";
            if (!groups[key]) groups[key] = [];
            groups[key].push(row);
        }
        return groups;
    }, [rows, platformIdx, columns]);

    const floatIds = Object.keys(groupedByFloat);
    const isMultiFloat = floatIds.length > 1;
    const useGL = rows.length > 10_000;
    const traceType = useGL ? "scattergl" : "scatter";

    // Build Plotly traces
    const traces = useMemo(() => {
        const result: Plotly.Data[] = [];
        const primaryVar = variableCols[0];
        const secondaryVar = variableCols.length > 1 ? variableCols[1] : null;

        for (let fi = 0; fi < floatIds.length; fi++) {
            const fid = floatIds[fi];
            const fRows = groupedByFloat[fid];

            const pressures = pressureKey
                ? fRows.map((r) => r[pressureKey] as number)
                : [];

            // Primary variable trace
            if (primaryVar) {
                const primaryKey = columns[colIdx(primaryVar)] ?? primaryVar;
                const values = fRows.map((r) => r[primaryKey] as number);

                const trace: Plotly.Data = {
                    x: values,
                    y: pressures,
                    type: traceType as Plotly.PlotType,
                    mode: "lines+markers",
                    name: isMultiFloat
                        ? `${label(primaryVar)} — ${fid}`
                        : label(primaryVar),
                    marker: isMultiFloat
                        ? {
                            color: FLOAT_COLORS[fi % FLOAT_COLORS.length],
                            size: 4,
                            opacity: 0.85,
                        }
                        : {
                            color: pressures,
                            colorscale: colorscale ? getColorscale(colorscale) : THERMAL,
                            size: 4,
                            opacity: 0.85,
                            showscale: !secondaryVar,
                            colorbar: !secondaryVar
                                ? { title: { text: "Pressure (dbar)", font: { size: 11 } }, thickness: 14, len: 0.6 }
                                : undefined,
                        },
                    line: isMultiFloat
                        ? { color: FLOAT_COLORS[fi % FLOAT_COLORS.length], width: 1.5 }
                        : { width: 1.5 },
                    xaxis: "x",
                    yaxis: "y",
                    hovertemplate: `${label(primaryVar)}: %{x}<br>Pressure: %{y} dbar<extra>${isMultiFloat ? fid : ""}</extra>`,
                };
                result.push(trace);
            }

            // Secondary variable trace (dual X-axis)
            if (secondaryVar) {
                const secKey = columns[colIdx(secondaryVar)] ?? secondaryVar;
                const secValues = fRows.map((r) => r[secKey] as number);

                const trace: Plotly.Data = {
                    x: secValues,
                    y: pressures,
                    type: traceType as Plotly.PlotType,
                    mode: "lines+markers",
                    name: isMultiFloat
                        ? `${label(secondaryVar)} — ${fid}`
                        : label(secondaryVar),
                    marker: {
                        color: isMultiFloat
                            ? FLOAT_COLORS[(fi + 5) % FLOAT_COLORS.length]
                            : "#E8785A",
                        size: 4,
                        opacity: 0.85,
                    },
                    line: {
                        color: isMultiFloat
                            ? FLOAT_COLORS[(fi + 5) % FLOAT_COLORS.length]
                            : "#E8785A",
                        width: 1.5,
                        dash: "dot",
                    },
                    xaxis: "x2",
                    yaxis: "y",
                    hovertemplate: `${label(secondaryVar)}: %{x}<br>Pressure: %{y} dbar<extra>${isMultiFloat ? fid : ""}</extra>`,
                };
                result.push(trace);
            }
        }

        return result;
    }, [
        floatIds, groupedByFloat, pressureKey, variableCols, columns,
        colIdx, isMultiFloat, traceType, colorscale,
    ]);

    // Layout
    const layout = useMemo((): Partial<Plotly.Layout> => {
        const primaryVar = variableCols[0];
        const secondaryVar = variableCols.length > 1 ? variableCols[1] : null;

        const base: Partial<Plotly.Layout> = {
            autosize: true,
            height: 480,
            margin: { t: secondaryVar ? 60 : 30, r: 40, b: 50, l: 70 },
            paper_bgcolor: "transparent",
            plot_bgcolor: "transparent",
            font: { family: "DM Sans, system-ui, sans-serif", size: 12, color: "#8BA5BC" },
            showlegend: isMultiFloat || !!secondaryVar,
            legend: {
                orientation: "h",
                yanchor: "bottom",
                y: 1.02,
                xanchor: "right",
                x: 1,
                font: { size: 11 },
                bgcolor: "transparent",
            },
            yaxis: {
                title: { text: "Pressure (dbar)", font: { size: 12 } },
                autorange: "reversed", // Hard Rule 2 — NON-NEGOTIABLE
                gridcolor: "rgba(139, 165, 188, 0.15)",
                zerolinecolor: "rgba(139, 165, 188, 0.2)",
                tickfont: { size: 11 },
            },
            xaxis: {
                title: { text: primaryVar ? label(primaryVar) : "", font: { size: 12 } },
                gridcolor: "rgba(139, 165, 188, 0.15)",
                zerolinecolor: "rgba(139, 165, 188, 0.2)",
                tickfont: { size: 11 },
                side: "bottom",
            },
        };

        if (secondaryVar) {
            (base as Record<string, unknown>).xaxis2 = {
                title: { text: label(secondaryVar), font: { size: 12 } },
                gridcolor: "rgba(139, 165, 188, 0.08)",
                tickfont: { size: 11 },
                overlaying: "x",
                side: "top",
            };
        }

        return base;
    }, [variableCols, isMultiFloat]);

    // Export handler (Hard Rule 10)
    const handleExport = useCallback(
        async (format: "png" | "svg") => {
            const gd = plotRef.current?.querySelector(".js-plotly-plot") as Plotly.PlotlyHTMLElement | null;
            if (!gd) return;
            const ts = new Date().toISOString().replace(/[:.]/g, "-");
            await Plotly.downloadImage(gd, {
                format,
                width: 1200,
                height: 800,
                filename: `floatchat_ocean_profile_${ts}`,
            } as Plotly.DownloadImgopts);
        },
        [],
    );

    return (
        <div
            ref={plotRef}
            className="relative w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3"
            role="img"
            aria-label="Ocean profile chart showing variables against depth/pressure"
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

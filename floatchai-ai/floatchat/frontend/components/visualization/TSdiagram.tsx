"use client";

/**
 * TSdiagram — Temperature-Salinity scatter diagram (Feature 6, Phase 5).
 *
 * X-axis = salinity (PSU), Y-axis = temperature (°C).
 * Points colored by pressure using the DEEP colorscale with colorbar.
 *
 * Hard Rule 5: Colorscales imported from lib/colorscales.ts.
 * Hard Rule 8: scattergl for datasets > 10,000 points.
 * Hard Rule 10: Export filenames include ISO timestamp.
 */

import React, { useRef, useCallback, useMemo } from "react";
import Plot from "react-plotly.js";
import Plotly from "plotly.js-dist-min";
import { Download } from "lucide-react";
import { DEEP, getColorscale } from "@/lib/colorscales";
import type { TSdiagramProps, ChartRow } from "@/types/visualization";

// ── Component ─────────────────────────────────────────────────────────────

export default function TSdiagram({
    rows,
    columns,
    colorscale,
    showDensityContours = false,
}: TSdiagramProps) {
    const plotRef = useRef<HTMLDivElement>(null);

    // Column name resolution (case-insensitive)
    const lowerCols = useMemo(() => columns.map((c) => c.toLowerCase()), [columns]);

    const findCol = useCallback(
        (name: string) => {
            const idx = lowerCols.findIndex((c) => c === name);
            return idx >= 0 ? columns[idx] : null;
        },
        [columns, lowerCols],
    );

    const salinityKey = findCol("salinity") ?? findCol("psal");
    const temperatureKey = findCol("temperature") ?? findCol("temp");
    const pressureKey = findCol("pressure") ?? findCol("pres");
    const platformKey = findCol("platform_number");
    const timestampKey = findCol("juld_timestamp") ?? findCol("juld");

    const useGL = rows.length > 10_000;
    const traceType = useGL ? "scattergl" : "scatter";

    // Build traces
    const traces = useMemo(() => {
        if (!salinityKey || !temperatureKey) return [];

        const salinities = rows.map((r) => r[salinityKey] as number);
        const temperatures = rows.map((r) => r[temperatureKey] as number);
        const pressures = pressureKey ? rows.map((r) => r[pressureKey] as number) : undefined;
        const platforms = platformKey ? rows.map((r) => String(r[platformKey] ?? "")) : undefined;
        const timestamps = timestampKey
            ? rows.map((r) => {
                const v = r[timestampKey];
                if (!v) return "";
                try { return new Date(v as string | number).toLocaleDateString(); } catch { return String(v); }
            })
            : undefined;

        // Build hover text
        const hoverText = rows.map((_, i) => {
            const parts = [
                `Temperature: ${temperatures[i]?.toFixed(2)} °C`,
                `Salinity: ${salinities[i]?.toFixed(2)} PSU`,
            ];
            if (pressures) parts.push(`Pressure: ${pressures[i]} dbar`);
            if (platforms) parts.push(`Float: ${platforms[i]}`);
            if (timestamps) parts.push(`Date: ${timestamps[i]}`);
            return parts.join("<br>");
        });

        const result: Plotly.Data[] = [
            {
                x: salinities,
                y: temperatures,
                type: traceType as Plotly.PlotType,
                mode: "markers",
                marker: {
                    size: 4,
                    opacity: 0.7,
                    color: pressures ?? "#4BAAC8",
                    colorscale: colorscale ? getColorscale(colorscale) : DEEP,
                    showscale: !!pressures,
                    colorbar: pressures
                        ? {
                            title: { text: "Pressure (dbar)", font: { size: 11 } },
                            thickness: 14,
                            len: 0.6,
                            tickfont: { size: 10 },
                        }
                        : undefined,
                    reversescale: true,
                },
                text: hoverText,
                hoverinfo: "text",
                showlegend: false,
            },
        ];

        // Optional density contours (sigma-t) — v1 default off
        if (showDensityContours && salinities.length > 0 && temperatures.length > 0) {
            const sMin = Math.floor(Math.min(...salinities));
            const sMax = Math.ceil(Math.max(...salinities));
            const tMin = Math.floor(Math.min(...temperatures));
            const tMax = Math.ceil(Math.max(...temperatures));
            const sRange: number[] = [];
            const tRange: number[] = [];
            for (let s = sMin; s <= sMax; s += 0.1) sRange.push(s);
            for (let t = tMin; t <= tMax; t += 0.1) tRange.push(t);

            // Simplified EOS: sigma-t ≈ rho(S,T,0) - 1000
            const z: number[][] = tRange.map((t) =>
                sRange.map((s) => {
                    const rho =
                        999.842594 +
                        6.793952e-2 * t -
                        9.095290e-3 * t ** 2 +
                        1.001685e-4 * t ** 3 -
                        1.120083e-6 * t ** 4 +
                        6.536332e-9 * t ** 5 +
                        (8.24493e-1 - 4.0899e-3 * t + 7.6438e-5 * t ** 2 - 8.2467e-7 * t ** 3 + 5.3875e-9 * t ** 4) * s +
                        (-5.72466e-3 + 1.0227e-4 * t - 1.6546e-6 * t ** 2) * s ** 1.5 +
                        4.8314e-4 * s ** 2;
                    return rho - 1000;
                }),
            );

            result.push({
                x: sRange,
                y: tRange,
                z,
                type: "contour",
                showscale: false,
                contours: {
                    coloring: "lines",
                    showlabels: true,
                    labelfont: { size: 9, color: "rgba(139,165,188,0.6)" },
                },
                line: { color: "rgba(139,165,188,0.3)", width: 1 },
                hoverinfo: "none",
                showlegend: false,
            } as Plotly.Data);
        }

        return result;
    }, [rows, salinityKey, temperatureKey, pressureKey, platformKey, timestampKey, traceType, colorscale, showDensityContours]);

    // Layout
    const layout = useMemo((): Partial<Plotly.Layout> => ({
        autosize: true,
        height: 480,
        margin: { t: 30, r: 80, b: 55, l: 65 },
        paper_bgcolor: "transparent",
        plot_bgcolor: "transparent",
        font: { family: "DM Sans, system-ui, sans-serif", size: 12, color: "#8BA5BC" },
        xaxis: {
            title: { text: "Salinity (PSU)", font: { size: 12 } },
            gridcolor: "rgba(139, 165, 188, 0.15)",
            zerolinecolor: "rgba(139, 165, 188, 0.2)",
            tickfont: { size: 11 },
        },
        yaxis: {
            title: { text: "Temperature (°C)", font: { size: 12 } },
            gridcolor: "rgba(139, 165, 188, 0.15)",
            zerolinecolor: "rgba(139, 165, 188, 0.2)",
            tickfont: { size: 11 },
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
                filename: `floatchat_ts_diagram_${ts}`,
            } as Plotly.DownloadImgopts);
        },
        [],
    );

    return (
        <div
            ref={plotRef}
            className="relative w-full rounded-lg border border-[var(--color-border-subtle)] bg-[var(--color-bg-surface)] p-3"
            role="img"
            aria-label="Temperature-Salinity diagram showing water mass characteristics"
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
